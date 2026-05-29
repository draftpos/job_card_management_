/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { SaleUpdateLineButton } from "@sale_management/interactions/sale_update_line_button";

patch(SaleUpdateLineButton.prototype, {
    setup() {
        const orderTable = this.el.querySelector("table#sales_order_table");
        if (!orderTable) {
            this.orderDetail = {};
            return;
        }
        return super.setup(...arguments);
    },
});
