"""The fixed numbers and names of intro videos, in one place."""

# The rules of an intro video (api-contract.md, "Media").
MAX_DURATION_SEC = 30
MAX_SIZE_BYTES = 50 * 1024 * 1024  # 50 MiB = 52 428 800 bytes
# Videos a user may have that are not deleted (loaded, posted or unposted).
MAX_ACTIVE_VIDEOS = 3

# Only MP4: what upload-url accepts, and the content type stored with every video.
MP4_CONTENT_TYPE = "video/mp4"
MP4_EXTENSION = "mp4"
# Every MP4 file starts with a "file type" box: 4 bytes that give its size, then the letters
# "ftyp" (bytes 4 to 7). confirm reads only these first 8 bytes of the file to check its type.
MP4_SIGNATURE = b"ftyp"
MP4_SIGNATURE_START = 4
MP4_SIGNATURE_END = 8

# Where a video is stored in the bucket: users/<user id>/intro/<random uuid>.mp4
UUID_PATTERN = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"

# How long the signed links work, in seconds: 15 min to upload, 5 min to watch.
UPLOAD_URL_EXPIRES_SEC = 900
VIEW_URL_EXPIRES_SEC = 300
MIN_URL_EXPIRES_SEC = 60
MAX_URL_EXPIRES_SEC = 3600

# Videos per page of the feed.
FEED_DEFAULT_LIMIT = 20
FEED_MAX_LIMIT = 50
# An employer (a user with an active company) sees only videos graded A or B.
EMPLOYER_FEED_RATINGS = ("A", "B")
# With job_id: the applicants still waiting for an answer come first.
WAITING_APPLICATION_STATUSES = ("submitted", "viewed")
