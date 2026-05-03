from odoo import models, fields, api

class Customer(models.Model):
    _name = 'customer'
    _description = 'Customer Master'
    _order = 'name'
    _inherit = ['mail.thread', 'mail.activity.mixin']  # Optional but useful

    name = fields.Char(string='Customer Name', required=True)
    customer_type = fields.Selection([
        ('main', 'Main Customer'),
        ('insurance', 'Insurance Company')
    ], string='Customer Type', required=True, default='main')
    
    # Link to native Odoo partner
    partner_id = fields.Many2one('res.partner', string='Linked Partner', ondelete='restrict', help='Linked Odoo Partner')
    
    # --- Contact Details ---
    email = fields.Char(string='Email')
    phone = fields.Char(string='Phone')
    website = fields.Char(string='Website')
    
    # --- Address ---
    street = fields.Char(string='Street')
    street2 = fields.Char(string='Street 2')
    city = fields.Char(string='City')
    state = fields.Char(string='State')
    zip_code = fields.Char(string='ZIP Code')
    country = fields.Char(string='Country')
    
    # --- Tax / Registration ---
    vat_number = fields.Char(string='VAT Number')
    registration_number = fields.Char(string='Registration Number')
    
    # --- Insurance Specific ---
    insurance_company_reg_no = fields.Char(string='Insurance Company Registration No')
    claims_contact_person = fields.Char(string='Claims Contact Person')
    claims_phone = fields.Char(string='Claims Phone')
    claims_email = fields.Char(string='Claims Email')
    
    # --- Banking ---
    bank_name = fields.Char(string='Bank Name')
    bank_account_number = fields.Char(string='Bank Account Number')
    bank_routing_number = fields.Char(string='Routing Number')
    
    # --- Notes ---
    notes = fields.Text(string='Notes')
    
    # --- Links to Vehicles ---
    vehicle_ids = fields.One2many('vehicle', 'customer_id', string='Vehicles Owned')

    @api.model_create_multi
    def create(self, vals_list):
        """Auto-create res.partner when customer is created"""
        for vals in vals_list:
            partner_vals = {
                'name': vals.get('name'),
                'email': vals.get('email'),
                'phone': vals.get('phone'),
                'street': vals.get('street'),
                'street2': vals.get('street2'),
                'city': vals.get('city'),
                'state_id': False,  # You can add state lookup if needed
                'zip': vals.get('zip_code'),
                'country_id': False,  # You can add country lookup if needed
                'vat': vals.get('vat_number'),
                'customer_rank': 1,
            }
            partner = self.env['res.partner'].create(partner_vals)
            vals['partner_id'] = partner.id
        return super(Customer, self).create(vals_list)

    def write(self, vals):
        """Update res.partner when customer is updated"""
        result = super(Customer, self).write(vals)
        for record in self:
            if record.partner_id:
                partner_vals = {
                    'name': vals.get('name', record.name),
                    'email': vals.get('email', record.email),
                    'phone': vals.get('phone', record.phone),
                    'street': vals.get('street', record.street),
                    'street2': vals.get('street2', record.street2),
                    'city': vals.get('city', record.city),
                    'zip': vals.get('zip_code', record.zip_code),
                    'vat': vals.get('vat_number', record.vat_number),
                }
                record.partner_id.write(partner_vals)
        return result