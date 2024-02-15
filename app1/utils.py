
import functools
import logging

# An async task decorator, since by default they don't report abnormal exits.
def log_uncaught(func):
    @functools.wraps(func)
    async def wrapped(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as ex:
            logging.exception('uncaught exception: %s', ex)
            raise

    return wrapped
