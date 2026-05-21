# Job Card Management (Odoo 19)

Odoo application module for automotive workshop operations: customers, vehicles, estimates, job cards, procurement, profitability, and dashboard reporting.

**Maintainer:** [@tatendatembojnr-code](https://github.com/tatendatembojnr-code)  
**Repository:** [draftpos/job_card_management_](https://github.com/draftpos/job_card_management_)

## Version

- **Odoo:** 19.0
- **Module version:** 19.0.2.0.1

## Features

- **Estimates** — Numbered quotes (EST-*), sectioned order lines (Parts, Repairs, Paint, Fittings, Labour), approval workflow, portal preview, email with PDF
- **Job cards** — Linked to estimates (JOB-*), mandatory schedule dates, technicians, insurance split invoicing
- **Vehicles** — Zimbabwe vehicle catalog (makes/models) + seeded fleet templates; display as `(REG) Make Model`
- **Customers** — Workshop customer master (separate from quick partner entry)
- **Procurement** — Requisitions from job card lines
- **Dashboard** — KPIs, overdue jobs, profitability views
- **Reports** — Estimate, job card, pick slip (sectioned), vehicle history

## Dependencies

`sale`, `purchase`, `purchase_requisition`, `stock`, `account`, `hr`, `hr_expense`, `mail`

## Installation

1. Copy this folder into your Odoo `addons` path (e.g. `addons/job_card_management`).
2. Update the apps list and install **Job Card Management**.
3. On upgrade, vehicle catalog and sample fleet records load from `data/vehicle_catalog_seed.xml` and `data/vehicle_records_seed.xml`.

```bash
odoo -c odoo.conf -d your_database -i job_card_management
# or upgrade:
odoo -c odoo.conf -d your_database -u job_card_management --stop-after-init
```

## Branching

| Branch | Purpose |
|--------|---------|
| `dev` | Active development |
| `main` | Release-aligned with `dev` (force-synced on release) |

## License

LGPL-3.0 (see module manifest).
