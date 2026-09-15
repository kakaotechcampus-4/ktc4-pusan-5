export type User = {
  id: number;
  nickname: string;
  email: string;
};

export type ApiErrorBody = {
  error: {
    code: string;
    message: string;
  };
};
