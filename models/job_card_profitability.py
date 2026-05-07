from odoo import models, fields


class JobCardProfitability(models.Model):
    _name = 'job.card.profitability'
    _description = 'Job Card Profitability'
    _auto = False
    _order = 'job_card_number desc'

    job_card_id = fields.Many2one('job.card', string='Job Card', readonly=True)
    job_card_number = fields.Char(string='Job Card Number', readonly=True)
    revenue = fields.Float(string='Revenue', readonly=True)
    labor_cost = fields.Float(string='Labor Cost', readonly=True)
    parts_cost = fields.Float(string='Parts Cost', readonly=True)
    expenses_cost = fields.Float(string='Expenses Cost', readonly=True)
    total_cost = fields.Float(string='Total Cost', readonly=True)
    net_profit = fields.Float(string='Net Profit', readonly=True)
    margin = fields.Float(string='Margin %', readonly=True)

    def init(self):
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW job_card_profitability AS (
                SELECT
                    jc.id AS id,
                    jc.id AS job_card_id,
                    jc.name AS job_card_number,
                    0.0 AS revenue,
                    COALESCE(labor.labor_cost, 0.0) AS labor_cost,
                    0.0 AS parts_cost,
                    0.0 AS expenses_cost,
                    COALESCE(labor.labor_cost, 0.0) AS total_cost,
                    0.0 - COALESCE(labor.labor_cost, 0.0) AS net_profit,
                    0.0 AS margin
                FROM job_card jc
                LEFT JOIN (
                    SELECT aal.account_id, SUM(ABS(COALESCE(aal.amount, 0.0))) AS labor_cost
                    FROM account_analytic_line aal
                    GROUP BY aal.account_id
                ) labor ON labor.account_id = jc.analytic_account_id
            )
        """)