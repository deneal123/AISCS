/** Import errors stay private; route recovery owns a bounded public failure. */
export default function routeLoader(load) {
  return async () => {
    try {
      return await load();
    } catch {
      throw Object.assign(new Error('Страница временно недоступна.'), { name: 'AppRouteLoadError' });
    }
  };
}
