import reflex as rx

from guiospro.settings import get_settings

config = rx.Config(
    app_name="guiospro",
    db_url=get_settings().database_url,
    plugins=[
        rx.plugins.SitemapPlugin(),
        rx.plugins.RadixThemesPlugin(theme=rx.theme(accent_color="teal", radius="medium")),
    ],
)
