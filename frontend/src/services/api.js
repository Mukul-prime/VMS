const BASE_URL = process.env.NEXT_PUBLIC_API_URL;

export const getCameras = async () => {
  const res = await fetch(`${BASE_URL}/cameras/`);
  return res.json();
};

export const getDetections = async () => {
  const res = await fetch(`${BASE_URL}/detect/`);
  return res.json();
};