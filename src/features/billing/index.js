// Публичный API фичи для ДРУГИХ фич — только виджеты и контекст.
// Страницы (BillingPage/BillingSuccessPage) здесь НЕ экспортируются намеренно:
// их подключает роутер напрямую (src/pages/**). Иначе любой импорт из этого
// барреля — например CreditsPill в шапке чата — тянул за собой BillingPage,
// а с ней recharts (~80 КБ gzip) на страницу, где нет ни одного графика.
export { default as CreditsPill } from './components/CreditsPill';
export { default as CreditSummary } from './components/CreditSummary';
export { useBalance } from './hooks/useBalance';
export { BillingProvider, useBillingContext, notifyBillingRefresh } from './context/BillingContext';
