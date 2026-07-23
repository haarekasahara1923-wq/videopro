import os
from loguru import logger

try:
    import cloudinary
    import cloudinary.uploader
    HAS_CLOUDINARY = True
except ImportError:
    HAS_CLOUDINARY = False


def is_cloudinary_configured() -> bool:
    if not HAS_CLOUDINARY:
        return False
    
    if os.getenv("CLOUDINARY_URL"):
        return True
    
    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME")
    api_key = os.getenv("CLOUDINARY_API_KEY")
    api_secret = os.getenv("CLOUDINARY_API_SECRET")
    return bool(cloud_name and api_key and api_secret)


def upload_to_cloudinary(file_path: str, resource_type: str = "auto", folder: str = "moneyprinterturbo") -> str:
    """
    Uploads a file to Cloudinary and returns the secure CDN URL.
    Returns None if Cloudinary is not configured or if upload fails.
    """
    if not is_cloudinary_configured():
        return None

    if not os.path.exists(file_path):
        logger.warning(f"Cloudinary upload skipped, file does not exist: {file_path}")
        return None

    try:
        if os.getenv("CLOUDINARY_URL"):
            cloudinary.config(cloudinary_url=os.getenv("CLOUDINARY_URL"))
        else:
            cloudinary.config(
                cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
                api_key=os.getenv("CLOUDINARY_API_KEY"),
                api_secret=os.getenv("CLOUDINARY_API_SECRET"),
                secure=True
            )

        logger.info(f"Uploading {file_path} to Cloudinary...")
        response = cloudinary.uploader.upload(
            file_path,
            resource_type=resource_type,
            folder=folder,
            overwrite=True
        )

        secure_url = response.get("secure_url")
        logger.info(f"Cloudinary upload successful: {secure_url}")
        return secure_url
    except Exception as e:
        logger.error(f"Failed to upload {file_path} to Cloudinary: {e}")
        return None
