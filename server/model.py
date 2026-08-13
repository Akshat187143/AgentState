from sqlmodel import SQLModel
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import Numeric, text
from sqlmodel import Field, SQLModel


class Product(SQLModel, table=True):
    **tablename** = "products"
    **table_args** = {"schema": "retail"}

    product_id: str = Field(primary_key=True)
    name: str
    category: str
    unit_price: Decimal = Field(sa_type=Numeric(10, 2))
    unit_cost: Decimal = Field(sa_type=Numeric(10, 2))
    min_order_qty: int
    lead_time_days: int
    shelf_life_days: int | None = None


class StockOnHand(SQLModel, table=True):
    **tablename** = "stock_on_hand"
    **table_args** = {"schema": "retail"}

    product_id: str = Field(primary_key=True)
    qty_on_hand: int
    stock_expiry_date: date | None = None
    updated_at: datetime = Field(
        sa_column_kwargs={"server_default": text("now()")}
    )


class SalesDaily(SQLModel, table=True):
    **tablename** = "sales_daily"
    **table_args** = {"schema": "retail"}

    product_id: str = Field(primary_key=True)
    sale_date: date = Field(primary_key=True)
    qty_sold: int
    revenue: Decimal = Field(sa_type=Numeric(12, 2))


class StockRequest(SQLModel, table=True):
    **tablename** = "stock_requests"
    **table_args** = {"schema": "app"}

    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(
        sa_column_kwargs={"server_default": text("now()")}
    )
    status: str = Field(default="submitted")
    source: str = Field(default="manual")
    note: str | None = None


class RequestLine(SQLModel, table=True):
    **tablename** = "request_lines"
    **table_args** = {"schema": "app"}

    id: int | None = Field(default=None, primary_key=True)
    request_id: int = Field(foreign_key="app.stock_requests.id")
    product_id: str
    qty: int


class StockPosition(SQLModel, table=True):
    """Read-only projection of retail.v_stock_position. Never written to."""

    **tablename** = "v_stock_position"
    **table_args** = {"schema": "retail"}

    product_id: str = Field(primary_key=True)
    name: str
    category: str
    qty_on_hand: int
    avg_daily_sales_7d: Decimal = Field(sa_type=Numeric(10, 2))
    days_of_cover: Decimal = Field(sa_type=Numeric(10, 1))
    lead_time_days: int
    suggested_order_qty: int
    stock_expiry_date: date | None = None
    revenue_7d: Decimal = Field(sa_type=Numeric(12, 2))
    units_7d: int
    status: str
