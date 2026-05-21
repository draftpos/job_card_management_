from odoo import fields, models


class JobCardBackendNavigationMixin(models.AbstractModel):
    _name = 'job.card.backend.navigation.mixin'
    _description = 'Odoo 19 backend form URL helper'

    backend_form_url = fields.Char(compute='_compute_backend_form_url')

    def _job_card_form_action_xmlid(self):
        return False

    def _compute_backend_form_url(self):
        for record in self:
            record.backend_form_url = False
            if not record.id:
                continue
            xmlid = record._job_card_form_action_xmlid()
            if not xmlid:
                continue
            action = self.env.ref(xmlid, raise_if_not_found=False)
            if action:
                record.backend_form_url = f'/odoo/action-{action.id}/{record.id}'
