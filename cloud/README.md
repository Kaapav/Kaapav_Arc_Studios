# Free cloud-GPU hero-shot lane

The local machine does the dependable work: script, Piper voice, captions,
FFmpeg, final assembly, review, and YouTube upload. The cloud is used only for
one or two 5-second motion inserts. If the cloud is unavailable, the final
video still renders from the original still images.

## Workflow

1. Render a normal draft locally with `--no-upload`.
2. Package at most two scenes:

   `.\\.venv\\Scripts\\python.exe cloud\\prepare_motion_job.py output\\<job-folder>`

3. Open `colab_wan_worker.py` in Google Colab, enable GPU, run it, upload the
   ZIP when prompted, and download `cloud_motion_results.zip`.
4. Attach the clips locally:

   `.\\.venv\\Scripts\\python.exe cloud\\apply_motion_results.py output\\<job-folder> cloud_motion_results.zip`

5. Build a review-only final copy:

   `.\\.venv\\Scripts\\python.exe cloud\\rerender_job.py output\\<job-folder>`

6. Review `video-cloud-motion.mp4` locally. Do not upload a cloud-rendered draft blindly.

The worker uses the official Wan2.1 T2V-1.3B model at 480P. T2V is used for
cutaway shots (phone screens, city lights, abstract AI visuals), not for
character continuity. Character scenes stay on consistent local story stills.
