import { CONSENT_DOCUMENT } from './consent';
import { OFFER_DOCUMENT } from './offer';
import { PRIVACY_DOCUMENT } from './privacy';

// Реестр правовых документов по slug из URL (/legal/:docId).
export const LEGAL_DOCUMENTS = {
  offer: OFFER_DOCUMENT,
  privacy: PRIVACY_DOCUMENT,
  consent: CONSENT_DOCUMENT,
};

export const getLegalDocument = (docId) => LEGAL_DOCUMENTS[docId] || null;
