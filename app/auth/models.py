from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class AuthenticatedIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str = Field(validation_alias=AliasChoices("id", "user_id"))
    email: str | None = None


class CurrentUser(AuthenticatedIdentity):
    role: str = ""
