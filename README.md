# Wedding photo QR

A mobile-friendly Streamlit app for guests to take a photo, upload it to one shared album, and view the other photos. The app uses a guest passcode and a **private** Supabase Storage bucket. The Supabase service-role key stays on the app server; never put it in browser code or commit it.

## How it works

1. A guest scans the QR code and opens the deployed HTTPS app.
2. They enter the shared guest passcode.
3. The page requests camera access and starts a rear-camera preview when the browser grants permission. Guests can switch to the front camera and expand the preview to full screen.
4. They tap **Take a photo**. The photo uploads automatically and appears in the shared album.
5. The couple shares the guest passcode separately from the QR code.

Mobile browsers require HTTPS and explicit camera permission. A website cannot take a photo silently; the guest must allow camera access and tap the shutter.

## Setup

1. Create a Supabase project and a **private** Storage bucket named `wedding-photos` (or configure another bucket name).
2. Install the dependencies with `python -m pip install -r requirements.txt`.
3. Create `.streamlit/secrets.toml` locally with:

   ```toml
   [app]
   passcode = "choose-a-long-guest-passcode"
   base_url = "https://your-deployed-app.example"

   [supabase]
   url = "https://your-project.supabase.co"
   service_role_key = "your-server-side-service-role-key"
   bucket = "wedding-photos"
   ```

   Keep this file private. It is excluded from Git. You can instead provide `APP_PASSCODE`, `APP_BASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, and `SUPABASE_BUCKET` as environment variables.

4. Start locally with `streamlit run streamlit_app.py`. Localhost is useful for testing; phone camera access and a usable QR require the deployed HTTPS URL.
5. Deploy the app to a host that supports Streamlit, add the same secrets through that host's secret manager, and set `app.base_url` to the final HTTPS app URL.
6. Open the app, enter the guest passcode, expand **Print or share the wedding QR code**, and download the QR image.

The gallery shows up to the latest 100 photos returned by Supabase Storage. Signed image links expire after one hour; refreshing the app creates new links.
