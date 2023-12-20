# from typing import Annotated, Any, Optional

# from litestar import get, post
# from litestar.connection import ASGIConnection
# from litestar.enums import RequestEncodingType
# from litestar.params import Body
# from litestar.response import Redirect
# from litestar.security.jwt import JWTAuth, Token

# from models import User


# async def retrieve_user_handler(
#     token: Token, connection: "ASGIConnection[Any, Any, Any, Any]", USER_DB
# ) -> Optional[User]:
#     return USER_DB.get(token.sub)


# # Login
# @get("/login")
# async def login() -> Template:
#     return Template(template_name="login.html", context={})


# @post("/login")
# async def login_handler(
#     data: Annotated[User, Body(media_type=RequestEncodingType.URL_ENCODED)],
# ) -> Response[User]:
#     MOCK_DB[str(data.name)] = data
#     jwt_auth.login(
#         identifier=str(data.name),
#         token_extras={"email": data.email},
#         response_body=data,
#     )
#     return Redirect(path="/dashboard")


# jwt_auth = JWTAuth[User](
#     retrieve_user_handler=retrieve_user_handler,
#     token_secret=environ.get("JWT_SECRET", "abcd1234"),
#     exclude=["/login", "/schema."],
# )
