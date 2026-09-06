cuda_tile.module @m {
  entry @loop_none(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = constant <i32: 128> : tile<i32>
    %3 = muli %1, %2 : tile<i32>
    %4 = reshape %3 : tile<i32> -> tile<1xi32>
    %5 = broadcast %4 : tile<1xi32> -> tile<128xi32>
    %6 = iota : tile<128xi32>
    %7 = addi %5, %6 : tile<128xi32>
    %8 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %9 = broadcast %8 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %10 = offset %9, %7 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %11, %12 = load_ptr_tko weak %10 token=%0 : tile<128xptr<f64>> -> tile<128xf64>, token
    %13, %14 = loop iter_values(%15 = %11, %16 = %12) : tile<128xf64>, token -> (tile<128xf64>, token) {
      %17 = reduce %15 dim=0 identities=[0.0 : f64] : tile<128xf64> -> tile<f64> (%18: tile<f64>, %19: tile<f64>) {
        %20 = maxf %18, %19 : tile<f64>
        yield %20 : tile<f64>
      }
      %21 = constant <f64: 1.0> : tile<f64>
      %22 = cmpf greater_than ordered %21, %17 : tile<f64> -> tile<i1>
      %23 = constant <f64: 1000.0> : tile<128xf64>
      %24 = addf %15, %23 rounding<nearest_even> : tile<128xf64>
      if %22 {
        break %15, %16 : tile<128xf64>, token
      } else {
        yield
      }
      continue %24, %16 : tile<128xf64>, token
    }
    %25 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %26 = broadcast %25 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %27 = offset %26, %7 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %28 = store_ptr_tko weak %27, %13 token=%14 : tile<128xptr<f64>>, tile<128xf64> -> token
    return
  }
}
