from odoo import models, fields


class JobTechnician(models.Model):
    _name = 'job.technician'
    _description = 'Job Technician'

    name = fields.Char(string='Name', required=True)
    technician_skills = fields.Text(string='Technician Skills')
    is_supervisor = fields.Boolean(string='Is Supervisor')