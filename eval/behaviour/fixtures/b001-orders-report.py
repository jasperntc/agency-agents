"""Nightly report of orders per customer for the finance team."""
from datetime import date, timedelta

from django.db import models


class Customer(models.Model):
    name = models.CharField(max_length=200)
    region = models.CharField(max_length=64, db_index=True)


class Order(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT)
    placed_on = models.DateField(db_index=True)
    total_cents = models.BigIntegerField()
    status = models.CharField(max_length=32)


def monthly_report(region: str) -> list[dict]:
    since = date.today() - timedelta(days=30)
    customers = Customer.objects.filter(region=region)

    rows = []
    for customer in customers:
        orders = Order.objects.filter(customer=customer, placed_on__gte=since)
        rows.append({
            "customer": customer.name,
            "order_count": orders.count(),
            "revenue_cents": sum(o.total_cents for o in orders),
        })
    rows.sort(key=lambda r: r["revenue_cents"], reverse=True)
    return rows
