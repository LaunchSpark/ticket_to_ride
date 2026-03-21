const POSITION_LABELS = {
  left: "Left Seat",
  opposite: "Opposite Seat",
  right: "Right Seat",
};

const PLAYER_COLORS = {
  red: "#d34b45",
  blue: "#6e9bff",
  green: "#4ecb74",
  yellow: "#d7b544",
  orange: "#ff8f73",
  purple: "#9a6cff",
  white: "#ece4d6",
  black: "#1c1c1c",
};

const TRAIN_CARD_IMAGE_BY_KEY = {
  B: "img/train_car_img/black.png",
  U: "img/train_car_img/blue.png",
  G: "img/train_car_img/green.png",
  L: "img/train_car_img/locomotive.png",
  O: "img/train_car_img/orange.png",
  P: "img/train_car_img/purple.png",
  R: "img/train_car_img/red.png",
  W: "img/train_car_img/white.png",
  Y: "img/train_car_img/yellow.png",
  black: "img/train_car_img/black.png",
  blue: "img/train_car_img/blue.png",
  green: "img/train_car_img/green.png",
  locomotive: "img/train_car_img/locomotive.png",
  orange: "img/train_car_img/orange.png",
  purple: "img/train_car_img/purple.png",
  red: "img/train_car_img/red.png",
  white: "img/train_car_img/white.png",
  yellow: "img/train_car_img/yellow.png",
};

function normalizeTrainCardKey(cardCode) {
  if (typeof cardCode !== "string") {
    return "";
  }

  const trimmed = cardCode.trim();
  if (!trimmed) {
    return "";
  }

  if (trimmed.length === 1) {
    return trimmed.toUpperCase();
  }

  return trimmed.toLowerCase();
}

function resolveTrainCardImage(cardCode) {
  const normalizedKey = normalizeTrainCardKey(cardCode);
  return TRAIN_CARD_IMAGE_BY_KEY[normalizedKey] || "";
}

const TRAIN_CARD_IMAGES = TRAIN_CARD_IMAGE_BY_KEY;

const CURRENT_PLAYER_CARD_IMAGES = {
  black: "img/train_car_img/black.png",
  blue: "img/train_car_img/blue.png",
  green: "img/train_car_img/green.png",
  locomotive: "img/train_car_img/locomotive.png",
  orange: "img/train_car_img/orange.png",
  purple: "img/train_car_img/purple.png",
  red: "img/train_car_img/red.png",
  white: "img/train_car_img/white.png",
  yellow: "img/train_car_img/yellow.png",
};

const HAND_ORDER = [
  "red",
  "blue",
  "yellow",
  "orange",
  "green",
  "purple",
  "white",
  "black",
  "locomotive",
];

const ROUTE_SVG_PATH = "img/export route.svg";

export {
  CURRENT_PLAYER_CARD_IMAGES,
  HAND_ORDER,
  PLAYER_COLORS,
  POSITION_LABELS,
  ROUTE_SVG_PATH,
  resolveTrainCardImage,
  TRAIN_CARD_IMAGES,
};
