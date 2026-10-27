// Deployment policy mirrors the backend profile; SimulatorPage verifies it over HTTP.
export const SIMULATION_PROFILE = process.env.REACT_APP_APPLICATION_PROFILE === 'simulation';
export const APPLICATION_HOME = SIMULATION_PROFILE ? '/simulator' : '/chat';
