# uvicorn logger
import logging
logger = logging.getLogger("uvicorn.error")

# let default be INFO
logger.setLevel(logging.INFO)