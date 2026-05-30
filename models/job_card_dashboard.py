from odoo import models, fields, api


class JobCardDashboard(models.Model):
    _name = 'job.card.dashboard'
    _description = 'Job Card Dashboard'
    _auto = False  # No DB table

    @api.model
    def get_dashboard_data(self, user_id=None, date_from=None, date_to=None, status=None):
        """Return all dashboard statistics with optional filters"""
        today = fields.Date.today()

        # Build domain filters
        estimate_domain = []
        job_domain = []
        procurement_domain = []

        if user_id:
            estimate_domain.append(('create_uid', '=', user_id))
            job_domain.append(('create_uid', '=', user_id))
            procurement_domain.append(('create_uid', '=', user_id))

        if date_from:
            estimate_domain.append(('create_date', '>=', date_from))
            job_domain.append(('create_date', '>=', date_from))
            procurement_domain.append(('create_date', '>=', date_from))

        if date_to:
            estimate_domain.append(('create_date', '<=', date_to))
            job_domain.append(('create_date', '<=', date_to))
            procurement_domain.append(('create_date', '<=', date_to))

        if status:
            if status == 'draft':
                estimate_domain.append(('state', '=', 'draft'))
                job_domain.append(('state', '=', 'draft'))
                procurement_domain.append(('state', '=', 'draft'))
            elif status == 'approved':
                estimate_domain.append(('state', '=', 'approved'))
                job_domain.append(('state', '=', 'approved'))
                procurement_domain.append(('state', 'in', ['approved', 'purchase_order_created']))
            elif status == 'in_progress':
                job_domain.append(('state', '=', 'in_progress'))
            elif status == 'completed':
                job_domain.append(('state', '=', 'completed'))
            elif status == 'delivered':
                job_domain.append(('state', '=', 'delivered'))

        # Estimates
        total_estimates = self.env['estimate'].search_count(estimate_domain)
        estimates_converted = self.env['estimate'].search_count(
            estimate_domain + [('state', '=', 'converted')]
        )

        # Job Cards
        jobs_in_progress = self.env['job.card'].search_count(
            job_domain + [('state', '=', 'in_progress')]
        )
        jobs_completed = self.env['job.card'].search_count(
            job_domain + [('state', '=', 'completed')]
        )
        jobs_delivered = self.env['job.card'].search_count(
            job_domain + [('state', '=', 'delivered')]
        )
        jobs_overdue = self.env['job.card'].search_count(
            job_domain + [
                ('end_date', '<', today),
                ('state', 'not in', ['completed', 'delivered', 'draft']),
            ]
        )

        # Requisitions
        reqs_in_progress = self.env['procurement'].search_count(
            procurement_domain + [('state', 'not in', ['draft', 'purchase_order_created'])]
        )

        # Invoices - filter by job cards matching the domain
        job_cards = self.env['job.card'].search(job_domain)
        job_cards_with_invoices = job_cards.filtered(lambda j: j.customer_invoice_id)

        total_invoices_done = len(job_cards_with_invoices.mapped('customer_invoice_id')) + \
                              len(job_cards_with_invoices.mapped('insurance_invoice_id'))

        # Payments
        invoice_ids = job_cards_with_invoices.mapped('customer_invoice_id').ids + \
                      job_cards_with_invoices.mapped('insurance_invoice_id').ids
        paid_invoices = self.env['account.move'].search([
            ('id', 'in', invoice_ids),
            ('payment_state', 'in', ['paid', 'in_payment']),
        ])
        total_payments_done = sum(paid_invoices.mapped('amount_total'))

        # Total Job Value & Profitability
        total_job_value = sum(job_cards.mapped('total_amount'))
        
        profitability_records = self.env['job.card.profitability'].search([('job_card_id', 'in', job_cards.ids)])
        total_profitability = sum(profitability_records.mapped('net_profit'))

        return {
            'total_estimates': total_estimates,
            'estimates_converted': estimates_converted,
            'jobs_in_progress': jobs_in_progress,
            'reqs_in_progress': reqs_in_progress,
            'total_payments_done': total_payments_done,
            'total_invoices_done': total_invoices_done,
            'jobs_completed': jobs_completed,
            'jobs_delivered': jobs_delivered,
            'jobs_overdue': jobs_overdue,
            'total_job_value': total_job_value,
            'total_profitability': total_profitability,
        }

    @api.model
    def get_overdue_jobs(self, user_id=None, date_from=None, date_to=None, status=None):
        """Return overdue job cards for the table with optional filters"""
        today = fields.Date.today()

        job_domain = [
            ('end_date', '<', today),
            ('state', 'not in', ['completed', 'delivered', 'draft']),
        ]

        if user_id:
            job_domain.append(('create_uid', '=', user_id))
        if date_from:
            job_domain.append(('create_date', '>=', date_from))
        if date_to:
            job_domain.append(('create_date', '<=', date_to))
        if status:
            if status in ['in_progress', 'approved']:
                job_domain.append(('state', '=', status))
            elif status in ['completed', 'delivered']:
                # completed and delivered are not overdue
                job_domain.append(('id', '=', False))

        overdue_jobs = self.env['job.card'].search(job_domain)

        state_selection = dict(self.env['job.card']._fields['state'].selection)

        res = []
        for job in overdue_jobs:
            state_label = state_selection.get(job.state, job.state)
            # Since all jobs in this list are overdue, we just append to the label
            state_label = f"{state_label} but Overdue"
            
            res.append({
                'id': job.id,
                'name': job.name,
                'customer': job.customer_id.name,
                'vehicle': job.vehicle_reg_number or job.vehicle_display or '',
                'start_date': str(job.start_date) if job.start_date else '',
                'end_date': str(job.end_date) if job.end_date else '',
                'state': state_label,
                'total_amount': job.total_amount,
            })
        return res