from pydantic import BaseModel, Field


class PricePerGramResponse(BaseModel):
    price_per_gram: float = Field(..., alias="pricePerGram")

    class Config:
        # allow both snake_case (internal) and camelCase (external)
        populate_by_name = True
        orm_mode = True
