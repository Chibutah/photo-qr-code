import base64
import binascii
import hmac
import os
import uuid
from datetime import datetime, timezone
from io import BytesIO
from urllib.parse import urlparse

import qrcode
import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError
from supabase import Client, create_client


st.set_page_config(
    page_title="Wedding photos",
    page_icon=":material/photo_camera:",
    layout="centered",
)

CAMERA_KEY = "wedding_camera"
MAX_PHOTO_BYTES = 8 * 1024 * 1024
CAMERA_HTML = """
<section class="camera-card">
  <div class="video-wrap">
    <video class="camera-video" autoplay playsinline muted></video>
    <div class="camera-placeholder">Your camera preview will appear here.</div>
  </div>
  <p class="camera-status" role="status">Requesting camera access…</p>
  <button class="capture-button" type="button" disabled>
    <span class="capture-dot"></span>
    Take a photo
  </button>
</section>
"""
CAMERA_CSS = """
.camera-card {
  color: var(--st-text-color);
  font-family: var(--st-font);
  display: grid;
  gap: 0.75rem;
}
.video-wrap {
  position: relative;
  overflow: hidden;
  aspect-ratio: 4 / 3;
  border-radius: 1rem;
  background: var(--st-secondary-background-color);
}
.camera-video {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: none;
}
.camera-placeholder {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  padding: 1.5rem;
  text-align: center;
  opacity: 0.72;
}
.camera-status {
  min-height: 1.25rem;
  margin: 0;
  font-size: 0.9rem;
  opacity: 0.8;
}
.capture-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.65rem;
  width: 100%;
  min-height: 3.25rem;
  border: 0;
  border-radius: 999px;
  background: var(--st-primary-color);
  color: var(--st-background-color);
  font: inherit;
  font-weight: 650;
  cursor: pointer;
}
.capture-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.capture-dot {
  width: 1rem;
  height: 1rem;
  border: 2px solid currentColor;
  border-radius: 50%;
}
"""
CAMERA_JS = """
const instances = new WeakMap();

export default function (component) {
  const { parentElement, data, setTriggerValue } = component;
  if (instances.has(parentElement)) {
    if (data?.status) {
      parentElement.querySelector(".camera-status").textContent = data.status;
    }
    return;
  }

  const video = parentElement.querySelector(".camera-video");
  const placeholder = parentElement.querySelector(".camera-placeholder");
  const status = parentElement.querySelector(".camera-status");
  const button = parentElement.querySelector(".capture-button");
  if (!video || !placeholder || !status || !button) return;

  let stream;
  let disposed = false;

  async function startCamera() {
    if (!navigator.mediaDevices?.getUserMedia) {
      status.textContent = "Camera access needs a secure HTTPS connection.";
      return;
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" } },
        audio: false,
      });
      if (disposed) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      video.srcObject = stream;
      await video.play();
      video.style.display = "block";
      placeholder.style.display = "none";
      button.disabled = false;
      status.textContent = "Ready when you are.";
    } catch (error) {
      status.textContent = error?.name === "NotAllowedError"
        ? "Allow camera access in your browser to take a photo."
        : "We couldn't start the camera. Check your browser permissions and try again.";
    }
  }

  button.addEventListener("click", () => {
    if (!video.videoWidth || !video.videoHeight) {
      status.textContent = "Wait for the camera preview, then try again.";
      return;
    }
    const canvas = document.createElement("canvas");
    const scale = Math.min(1, 1600 / video.videoWidth);
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
    setTriggerValue("photo", canvas.toDataURL("image/jpeg", 0.82));
    status.textContent = "Uploading your photo…";
  });

  const cleanup = () => {
    disposed = true;
    stream?.getTracks().forEach((track) => track.stop());
    instances.delete(parentElement);
  };
  instances.set(parentElement, cleanup);
  startCamera();
  return cleanup;
}
"""

_CAMERA = st.components.v2.component(
    "wedding_camera",
    html=CAMERA_HTML,
    css=CAMERA_CSS,
    js=CAMERA_JS,
)


def get_settings() -> dict[str, dict[str, str]]:
    try:
        return {
            "app": dict(st.secrets.get("app", {})),
            "supabase": dict(st.secrets.get("supabase", {})),
        }
    except StreamlitSecretNotFoundError:
        return {"app": {}, "supabase": {}}


def setting(settings: dict[str, dict[str, str]], section: str, key: str, env: str) -> str:
    return os.environ.get(env, settings.get(section, {}).get(key, "")).strip()


def get_supabase_client(url: str, service_role_key: str) -> Client:
    return create_client(url, service_role_key)


def qr_code_image(url: str) -> BytesIO:
    code = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    code.add_data(url)
    code.make(fit=True)
    image = code.make_image(fill_color="#493a35", back_color="white").convert("RGB")
    output = BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return output


def upload_photo(client: Client, bucket: str, data_url: str) -> None:
    header, separator, encoded = data_url.partition(",")
    if not separator or header != "data:image/jpeg;base64":
        raise ValueError("The camera returned an unsupported photo format.")
    try:
        photo = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("The photo could not be read. Please take it again.") from error
    if not photo:
        raise ValueError("The photo is empty. Please take it again.")
    if len(photo) > MAX_PHOTO_BYTES:
        raise ValueError("This photo is too large to upload. Please take it again.")

    now = datetime.now(timezone.utc)
    object_name = f"{now:%Y%m%d-%H%M%S}-{uuid.uuid4().hex}.jpg"
    client.storage.from_(bucket).upload(
        object_name,
        photo,
        file_options={"content-type": "image/jpeg", "upsert": "false"},
    )


def get_gallery(client: Client, bucket: str) -> list[tuple[str, str]]:
    objects = client.storage.from_(bucket).list(
        "",
        {
            "limit": 100,
            "offset": 0,
            "sortBy": {"column": "created_at", "order": "desc"},
        },
    )
    photos = [
        item["name"]
        for item in objects
        if item.get("name") and item["name"] != ".emptyFolderPlaceholder"
    ]
    signed_photos = []
    for name in photos:
        signed_url = client.storage.from_(bucket).create_signed_url(name, 3600)
        signed_photos.append((name, signed_url["signedURL"]))
    return signed_photos


settings = get_settings()
passcode = setting(settings, "app", "passcode", "APP_PASSCODE")
base_url = setting(settings, "app", "base_url", "APP_BASE_URL")
supabase_url = setting(settings, "supabase", "url", "SUPABASE_URL")
service_role_key = setting(settings, "supabase", "service_role_key", "SUPABASE_SERVICE_ROLE_KEY")
bucket = setting(settings, "supabase", "bucket", "SUPABASE_BUCKET") or "wedding-photos"

st.title("A little piece of our day")
st.write("Take a photo and share it with everyone celebrating with us.")

missing_settings = []
if not passcode:
    missing_settings.append("a guest passcode")
if not supabase_url or not service_role_key:
    missing_settings.append("Supabase URL and service-role key")
if missing_settings:
    st.info(
        "Finish setup to open the guest photo page: add "
        + " and ".join(missing_settings)
        + ". See the setup instructions in README.md."
    )
    st.stop()

if "guest_access_granted" not in st.session_state:
    st.session_state.guest_access_granted = False

if not st.session_state.guest_access_granted:
    with st.form("guest_access"):
        entered_passcode = st.text_input(
            "Guest passcode",
            type="password",
            autocomplete="current-password",
        )
        submitted = st.form_submit_button("Open the photo page", type="primary")
    if submitted:
        if hmac.compare_digest(entered_passcode, passcode):
            st.session_state.guest_access_granted = True
            st.rerun()
        st.error("That passcode doesn't match. Please check with the couple.")
    st.stop()

client = get_supabase_client(supabase_url, service_role_key)
st.subheader("Take a photo")
st.caption("Your camera will start after you allow access. Tap the shutter to upload your photo.")
camera_status = st.session_state.pop("camera_status_message", "")
camera_result = _CAMERA(
    key=CAMERA_KEY,
    data={"status": camera_status},
    on_photo_change=lambda: None,
)

if camera_result.photo:
    try:
        upload_photo(client, bucket, camera_result.photo)
    except ValueError as error:
        st.error(str(error))
        st.session_state.camera_status_message = str(error)
    except Exception as error:
        st.error(f"Your photo couldn't be uploaded. Please try again. ({error})")
        st.session_state.camera_status_message = "The upload failed. Please try taking the photo again."
    else:
        st.success("Your photo is in the shared album.")
        st.session_state.camera_status_message = "Your photo was added to the shared album."
    st.rerun()

st.subheader("Shared album")
try:
    gallery_photos = get_gallery(client, bucket)
except Exception as error:
    st.error(f"The shared album couldn't be loaded. Please try again later. ({error})")
else:
    if not gallery_photos:
        st.caption("The first photos will appear here.")
    else:
        columns = st.columns(2)
        for index, (name, signed_url) in enumerate(gallery_photos):
            with columns[index % len(columns)]:
                st.image(signed_url, caption=name, width="stretch")

with st.expander("Print or share the wedding QR code"):
    parsed_url = urlparse(base_url)
    if parsed_url.scheme != "https" or not parsed_url.netloc:
        st.info("Set app.base_url to the deployed HTTPS address to create a guest QR code.")
    else:
        qr_image = qr_code_image(base_url)
        st.image(qr_image.getvalue(), caption="Scan to open the wedding photo page")
        st.download_button(
            "Download QR code",
            data=qr_image.getvalue(),
            file_name="wedding-photo-qr.png",
            mime="image/png",
        )
        st.caption("Share the guest passcode separately from this QR code.")
