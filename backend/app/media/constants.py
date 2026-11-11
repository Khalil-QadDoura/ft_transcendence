"""The fixed numbers and names of intro videos, avatars and company logos, in one place."""

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
# The largest id the database can hold (BIGINT): a bigger cursor can be no video's id.
MAX_ID = 2**63 - 1
# An employer (a user with an active company) sees only videos graded A or B.
EMPLOYER_FEED_RATINGS = ("A", "B")
# With job_id: the applicants still waiting for an answer come first.
WAITING_APPLICATION_STATUSES = ("submitted", "viewed")

# --- Avatars and company logos (BE-08) -----------------------------------------------------

# The two folders anyone may download from without a signed link (the bucket's anonymous
# policy, INF-04). An avatar is avatars/<user id>/<uuid>.<ext>, a logo logos/<company id>/...
# Only the server writes there: no upload link ever points into them.
AVATARS_FOLDER = "avatars"
LOGOS_FOLDER = "logos"
# The browser uploads into this private folder instead, e.g. staging/avatars/<user id>/...
# Nobody can download from it. confirm checks the file there, then the server writes a copy
# of it under a new name in the public folder.
STAGING_FOLDER = "staging"
# The picture types we accept: extension -> the Content-Type the server stores with the public
# copy, which MinIO sends back to everyone who downloads it.
PICTURE_TYPES = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
# The name Pillow (the image library) gives each type.
PICTURE_FORMATS = {"jpg": "JPEG", "png": "PNG", "webp": "WEBP"}
DEFAULT_PICTURE_EXTENSION = "jpg"
# Neither the contract nor the reference has a limit; 5 MiB takes any phone photo as it is.
MAX_PICTURE_BYTES = 5 * 1024 * 1024  # 5 MiB = 5 242 880 bytes
# The row lock that a picture confirm and the deletion of its account or company take
# (SQLAlchemy's name for PostgreSQL's SELECT ... FOR NO KEY UPDATE). Like FOR UPDATE, two
# requests cannot hold it on the same row at once, but it still lets PostgreSQL check that
# other rows point at a real row (a foreign key). With FOR UPDATE, DELETE /companies, whose
# second UPDATE of the company has PostgreSQL check that its users exist, and a logo confirm
# holding the owner's row would each wait for the other forever (a deadlock).
ROW_LOCK = {"key_share": True}
# A small file can still be a huge picture that takes gigabytes of memory to decode (a
# "decompression bomb"). 25 million pixels is a 24-megapixel camera photo (6000 x 4000).
MAX_PICTURE_PIXELS = 25_000_000
