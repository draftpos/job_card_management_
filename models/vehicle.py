from odoo import models, fields, api

class Vehicle(models.Model):
    _name = 'vehicle'
    _description = 'Vehicle Master'
    _order = 'name'

    # --- Vehicle Identification ---
    name = fields.Char(string='Vehicle Name', required=True)
    registration_number = fields.Char(string='Registration Number', required=True)
    chassis_number = fields.Char(string='Chassis / VIN Number', required=True)
    engine_number = fields.Char(string='Engine Number', required=True)
    make = fields.Char(string='Make', required=True)
    model = fields.Char(string='Model', required=True)
    year_of_manufacture = fields.Integer(string='Year of Manufacture', required=True)

    # --- Vehicle Specifications ---
    engine_type_code = fields.Char(string='Engine Type/Code')
    transmission = fields.Selection([
        ('manual', 'Manual'),
        ('automatic', 'Automatic'),
        ('cvt', 'CVT'),
        ('other', 'Other')
    ], string='Transmission', required=True)
    drive_type = fields.Selection([
        ('fwd', 'Front Wheel Drive'),
        ('rwd', 'Rear Wheel Drive'),
        ('awd', 'All Wheel Drive'),
        ('4wd', '4 Wheel Drive')
    ], string='Drive Type', required=True)
    fuel_type = fields.Selection([
        ('petrol', 'Petrol'),
        ('diesel', 'Diesel'),
        ('electric', 'Electric'),
        ('hybrid', 'Hybrid'),
        ('cng', 'CNG'),
        ('lpg', 'LPG')
    ], string='Fuel Type', required=True)
    odometer_reading = fields.Float(string='Odometer Reading (km/miles)')

    # --- Service Specifics ---
    reason_for_service = fields.Text(string='Reason for Service')
    last_service_date = fields.Date(string='Last Service Date')
    last_service_mileage = fields.Float(string='Last Service Mileage')
    known_repairs = fields.Text(string='Known Repairs or Modifications')
    specific_concerns = fields.Text(string='Any Specific Concerns')

    # --- Links to customer model (not res.partner) ---
    customer_id = fields.Many2one('customer', string='Owner Customer')
    insurance_customer_id = fields.Many2one('customer', string='Insurance Customer')