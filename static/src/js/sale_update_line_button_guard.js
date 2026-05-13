odoo.define('job_card_management.sale_update_line_button_guard', function (require) {
    'use strict';

    const { SaleUpdateLineButton } = require('@sale_management/interactions/sale_update_line_button');

    const originalSetup = SaleUpdateLineButton.prototype.setup;
    SaleUpdateLineButton.prototype.setup = function () {
        const orderTable = this.el.querySelector('table#sales_order_table');
        if (!orderTable) {
            this.orderDetail = {};
            return;
        }
        return originalSetup.apply(this, arguments);
    };
});
