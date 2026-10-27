import { request } from './request';

const path = (threadId, question) => `/api/chats/${encodeURIComponent(threadId)}/runs/${question.source_job_id}/questions/${question.question_id}`;
export const readHumanQuestion = (threadId, question, signal) =>
  request({ method: 'get', url: path(threadId, question), signal, __skipRetry: true });
export const answerHumanQuestion = (threadId, question, payload) =>
  request({ method: 'post', url: `${path(threadId, question)}/answer`, data: payload, __skipRetry: true });
export const cancelHumanQuestion = (threadId, question) =>
  request({ method: 'post', url: `${path(threadId, question)}/cancel`, data: {}, __skipRetry: true });
export const readHumanQuestionCost = (threadId, question, signal) =>
  request({ method: 'get', url: `${path(threadId, question)}/cost`, signal, __skipRetry: true });
export const decideHumanQuestionCost = (threadId, question, payload) =>
  request({ method: 'post', url: `${path(threadId, question)}/cost`, data: payload, __skipRetry: true });
