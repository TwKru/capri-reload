"""Connect a running Colab voice session; the password is entered without echo."""
import argparse
from getpass import getpass

from capri.audio.colab_backend import configure

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?")
    args = parser.parse_args()
    url = args.url or input("HTTPS-ссылка Gradio из Colab: ").strip()
    configure(url, getpass("Пароль голоса из Colab: "))
    print("Colab подключён. Перезапустите Капри.")
