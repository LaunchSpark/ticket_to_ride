import { ROUTE_SVG_PATH } from "../constants.jsx";

const routeMarkupCache = {
  promise: null,
};

function loadRouteSvgMarkup() {
  if (!routeMarkupCache.promise) {
    routeMarkupCache.promise = fetch(ROUTE_SVG_PATH)
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Route SVG request failed with status ${response.status}`);
        }
        return response.text();
      })
      .catch((error) => {
        console.error(error);
        return "";
      });
  }

  return routeMarkupCache.promise;
}

export { loadRouteSvgMarkup };
