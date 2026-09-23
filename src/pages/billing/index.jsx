// Страница подключается напрямую, минуя баррель фичи: баррель — публичный API
// для других фич (виджеты), и страницы в нём тянули бы recharts в чужие чанки.
import BillingPage from '@features/billing/page/BillingPage';

export default BillingPage;
