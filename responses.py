class StandardResponse:
    @staticmethod
    def success(data=None, message=""):
        return {
            "success": True,
            "data": data,
            "message": message,
        }

    @staticmethod
    def error(message, data=None):
        return {
            "success": False,
            "data": data,
            "message": message,
        }
