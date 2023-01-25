export async function api(url) {
    const response = await fetch(url);
    if (response.ok) {
      const jsonValue = await response.json();
      return Promise.resolve(jsonValue);
    } else {
      return Promise.reject('Response was not OK.');
    }
  }

export async function getSession(sessionId) {
    return await api(`/api/sessions/${sessionId}/`); 
  }

  export async function getSessionList() {
    return await api(`/api/sessions/`); 
  }