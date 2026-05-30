/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, onWillStart } from "@odoo/owl";

class JobCardDashboard extends Component {
    static template = "job_card_management.JobCardDashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");

        this.state = useState({
            data: {},
            overdueJobs: [],
            users: [],
            formattedPayments: "$ 0.00",
            formattedJobValue: "$ 0.00",
            formattedProfitability: "$ 0.00",
            formattedJobAmounts: {},
            loading: true,
            filters: {
                user_id: "0",
                date_range: "",
                date_from: "",
                date_to: "",
                status: "",
            },
        });

        onWillStart(async () => {
            await Promise.all([this.loadUsers(), this.loadData()]);
        });
    }

    async loadUsers() {
        try {
            const users = await this.orm.searchRead("res.users", [], ["id", "name"]);
            this.state.users = users;
        } catch (e) {
            this.state.users = [];
        }
    }

    onDateRangeChange() {
        const range = this.state.filters.date_range;
        const now = new Date();
        const fmt = (d) => d.toISOString().split('T')[0];

        if (range === 'today') {
            this.state.filters.date_from = fmt(now);
            this.state.filters.date_to = fmt(now);
        } else if (range === 'yesterday') {
            const y = new Date(now);
            y.setDate(y.getDate() - 1);
            this.state.filters.date_from = fmt(y);
            this.state.filters.date_to = fmt(y);
        } else if (range === 'this_week') {
            const start = new Date(now);
            const day = start.getDay();
            const diff = day === 0 ? -6 : 1 - day;
            start.setDate(start.getDate() + diff);
            this.state.filters.date_from = fmt(start);
            this.state.filters.date_to = fmt(now);
        } else if (range === 'last_week') {
            const start = new Date(now);
            const day = start.getDay();
            const diff = day === 0 ? -13 : -6 - day;
            start.setDate(start.getDate() + diff);
            const end = new Date(start);
            end.setDate(end.getDate() + 6);
            this.state.filters.date_from = fmt(start);
            this.state.filters.date_to = fmt(end);
        } else if (range === 'this_month') {
            this.state.filters.date_from = fmt(new Date(now.getFullYear(), now.getMonth(), 1));
            this.state.filters.date_to = fmt(now);
        } else if (range === 'last_month') {
            this.state.filters.date_from = fmt(new Date(now.getFullYear(), now.getMonth() - 1, 1));
            this.state.filters.date_to = fmt(new Date(now.getFullYear(), now.getMonth(), 0));
        } else if (range === 'this_year') {
            this.state.filters.date_from = fmt(new Date(now.getFullYear(), 0, 1));
            this.state.filters.date_to = fmt(now);
        } else if (range === '') {
            this.state.filters.date_from = "";
            this.state.filters.date_to = "";
        }
        // If range is 'custom', keep whatever dates are already set

        this.loadData();
    }

    async loadData() {
        this.state.loading = true;
        try {
            const kwargs = {};

            if (this.state.filters.user_id && this.state.filters.user_id !== "0") {
                kwargs.user_id = parseInt(this.state.filters.user_id, 10);
            }
            if (this.state.filters.date_from) {
                kwargs.date_from = this.state.filters.date_from;
            }
            if (this.state.filters.date_to) {
                kwargs.date_to = this.state.filters.date_to;
            }
            if (this.state.filters.status) {
                kwargs.status = this.state.filters.status;
            }

            const [data, overdueJobs] = await Promise.all([
                this.orm.call("job.card", "get_dashboard_data", [], kwargs),
                this.orm.call("job.card", "get_overdue_jobs", [], kwargs),
            ]);

            this.state.data = data || {};
            this.state.overdueJobs = overdueJobs || [];

            this.state.formattedPayments = this.formatCurrency(data.total_payments_done);
            this.state.formattedJobValue = this.formatCurrency(data.total_job_value);
            this.state.formattedProfitability = this.formatCurrency(data.total_profitability);

            const amounts = {};
            for (const job of this.state.overdueJobs) {
                amounts[job.id] = this.formatCurrency(job.total_amount);
            }
            this.state.formattedJobAmounts = amounts;
        } catch (e) {
            console.error("Dashboard load error:", e);
        } finally {
            this.state.loading = false;
        }
    }

    formatCurrency(amount) {
        const value = amount || 0;
        return "$ " + value.toLocaleString("en-US", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    }

    openJobCard(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "job.card",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    _getCommonDomain() {
        const domain = [];
        if (this.state.filters.user_id && this.state.filters.user_id !== "0") {
            domain.push(["create_uid", "=", parseInt(this.state.filters.user_id, 10)]);
        }
        if (this.state.filters.date_from) {
            domain.push(["create_date", ">=", this.state.filters.date_from]);
        }
        if (this.state.filters.date_to) {
            domain.push(["create_date", "<=", this.state.filters.date_to]);
        }
        return domain;
    }

    _getStatusDomain(status) {
        if (!status) return [];
        if (status === 'draft') return [["state", "=", "draft"]];
        if (status === 'approved') return [["state", "=", "approved"]];
        if (status === 'in_progress') return [["state", "=", "in_progress"]];
        if (status === 'completed') return [["state", "=", "completed"]];
        if (status === 'delivered') return [["state", "=", "delivered"]];
        return [];
    }

    openAction(res_model, name, extra_domain = []) {
        let domain = this._getCommonDomain();
        if (res_model === 'estimate' || res_model === 'job.card') {
            domain = domain.concat(this._getStatusDomain(this.state.filters.status));
        }
        if (res_model === 'procurement') {
            if (this.state.filters.status === 'approved') {
                domain.push(["state", "in", ["approved", "purchase_order_created"]]);
            } else {
                domain = domain.concat(this._getStatusDomain(this.state.filters.status));
            }
        }
        if (res_model === 'account.move' || res_model === 'account.payment' || res_model === 'job.card.profitability') {
            domain = []; // Keep it simple for related models without complex joins
        }
        if (extra_domain.length > 0) {
            domain = domain.concat(extra_domain);
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: name,
            res_model: res_model,
            domain: domain,
            views: [[false, "list"], [false, "form"]],
            target: "current",
        });
    }
}

registry.category("actions").add("job_card_management.dashboard", JobCardDashboard);