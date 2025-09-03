import logging
from logging.handlers import RotatingFileHandler
import os

logger = logging.getLogger("hogbot")
logger.setLevel(logging.INFO)
handler = RotatingFileHandler(
    filename=os.path.join("data", "hogbot.log"),
    mode='a',
    maxBytes=5*1024*1024,
    backupCount=2,
    encoding='utf-8',
    delay=0
)
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)