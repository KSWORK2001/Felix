import os
import webview

from backend.api import Api


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    web_dir = os.path.join(base_dir, "web")
    api = Api(base_dir=base_dir)

    window = webview.create_window(
        "AI Secretary",
        url=os.path.join(web_dir, "index.html"),
        js_api=api,
        width=1200,
        height=800,
    )

    webview.start(gui="edgechromium", debug=True, http_server=True)


if __name__ == "__main__":
    main()
