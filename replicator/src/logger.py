import time
import os

class Logger:
    BLUE = "\033[94m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    RESET = "\033[0m"
    BOLD = "\033[1m"
    PINK = "\033[95m"

    @staticmethod
    def _get_time():
        return time.strftime("%H:%M:%S")

    @staticmethod
    def _log(tag, message, color="", indent=0):
        t = Logger._get_time()
        ind = "  " * indent
        print(f"[{t}] {color}[{tag:<7}]{Logger.RESET} {ind}{message}")

    @staticmethod
    def info(message, indent=0):
        Logger._log("INFO", message, indent=indent)

    @staticmethod
    def success(message, indent=0):
        Logger._log("SUCCESS", message, color=Logger.GREEN, indent=indent)

    @staticmethod
    def warn(message, indent=0):
        Logger._log("WARN", message, color=Logger.YELLOW, indent=indent)

    @staticmethod
    def error(message, indent=0, exc=None):
        msg = f"{message}"
        if exc:
            msg += f": {str(exc)}"
        Logger._log("ERROR", msg, color=Logger.RED, indent=indent)

    @staticmethod
    def scan(message, indent=0):
        Logger._log("SCAN", message, color=Logger.BLUE, indent=indent)

    @staticmethod
    def schema(message, indent=0):
        Logger._log("SCHEMA", message, color=Logger.CYAN, indent=indent)

    @staticmethod
    def process(message, indent=0):
        Logger._log("PROCESS", message, color=Logger.BOLD, indent=indent)

    @staticmethod
    def heartbeat(message, indent=0):
        Logger._log("HEART", message, color=Logger.PINK, indent=indent)

if __name__ == "__main__":
    Logger.info("Starting Logger test...")
    Logger.success("Connection established.")
    Logger.warn("Disk space low.")
    Logger.error("Failed to insert row", exc="ODBC Error 123")
    Logger.scan("Checking tables...")
    Logger.schema("Adding column [id] to table [test]")
    Logger.process("Batch of 500 records synced.")
    Logger.heartbeat("Replicator is idle.")
