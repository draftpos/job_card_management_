import json

from odoo import http
from odoo.http import request


class JobCardReportController(http.Controller):
    """Legacy PDF preview endpoint (kept for compatibility). Print uses /report/pdf/ directly."""

    @http.route('/job_card_management/report/preview', type='http', auth='user', methods=['POST'], csrf=False)
    def report_preview(self, **kwargs):
        data = json.loads(request.httprequest.data)
        record_id = int(data.get('record_id', 0))
        report_xml_id = data.get('report_name', '')

        if not record_id or not report_xml_id:
            return request.not_found()

        report_action = request.env['ir.actions.report'].search([
            ('report_name', '=', report_xml_id),
        ], limit=1)
        if not report_action:
            try:
                report_action = request.env.ref(report_xml_id)
            except Exception:
                report_action = False
        if not report_action:
            report_action = request.env['ir.actions.report'].search([
                '|',
                ('report_name', '=', report_xml_id),
                ('report_file', '=', report_xml_id),
            ], limit=1)

        if not report_action:
            return request.make_response(
                json.dumps({'error': f'Report not found: {report_xml_id}'}),
                [('Content-Type', 'application/json')],
            )

        pdf_content, _ = request.env['ir.actions.report']._render_qweb_pdf(
            report_action.report_name, [record_id],
        )
        return request.make_response(pdf_content, [
            ('Content-Type', 'application/pdf'),
            ('Content-Length', str(len(pdf_content))),
        ])
