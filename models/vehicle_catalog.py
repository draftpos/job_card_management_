from odoo import api, fields, models


class VehicleMake(models.Model):
    _name = "vehicle.make"
    _description = "Vehicle Make"
    _order = "name"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    model_ids = fields.One2many("vehicle.model", "make_id", string="Models")

    _sql_constraints = [
        ("vehicle_make_name_uniq", "unique(name)", "Vehicle make must be unique."),
    ]


class VehicleModel(models.Model):
    _name = "vehicle.model"
    _description = "Vehicle Model"
    _order = "make_id, name"

    name = fields.Char(required=True)
    make_id = fields.Many2one("vehicle.make", required=True, ondelete="cascade")
    year_from = fields.Integer(string="Year From")
    year_to = fields.Integer(string="Year To")
    body_type = fields.Char(string="Body Type")
    fuel_type = fields.Selection(
        [
            ("petrol", "Petrol"),
            ("diesel", "Diesel"),
            ("hybrid", "Hybrid"),
            ("electric", "Electric"),
        ],
        string="Fuel Type",
    )
    display_name = fields.Char(compute="_compute_display_name", store=True)

    @api.depends("name", "make_id.name", "year_from", "year_to")
    def _compute_display_name(self):
        for rec in self:
            label = rec.name or ""
            if rec.make_id:
                label = f"{rec.make_id.name} {label}".strip()
            if rec.year_from and rec.year_to:
                label = f"{label} ({rec.year_from}-{rec.year_to})"
            elif rec.year_from:
                label = f"{label} ({rec.year_from})"
            rec.display_name = label

    _sql_constraints = [
        (
            "vehicle_model_make_name_uniq",
            "unique(make_id, name)",
            "Model must be unique per make.",
        ),
    ]
