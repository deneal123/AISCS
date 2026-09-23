import { mapApiError } from '../../api/dtoMappers';

export const normalizeDomainError = (error, options) => mapApiError(error, options);
export const getErrorMessage = (error, options) => normalizeDomainError(error, options).message;
