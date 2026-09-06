cuda_tile.module @m {
  entry @loop_until(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
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
    %13 = constant <f64: 0.5> : tile<128xf64>
    %14 = constant <f64: 1.0> : tile<128xf64>
    %15 = constant <f64: 1.0> : tile<128xf64>
    %16 = constant <f64: 0.0> : tile<128xf64>
    %17, %18, %19 = loop iter_values(%20 = %15, %21 = %16, %22 = %12) : tile<128xf64>, tile<128xf64>, token -> (tile<128xf64>, tile<128xf64>, token) {
      %23 = mulf %20, %20 rounding<nearest_even> : tile<128xf64>
      %24 = subf %23, %11 rounding<nearest_even> : tile<128xf64>
      %25 = absf %24 : tile<128xf64>
      %26 = reduce %25 dim=0 identities=[0.0 : f64] : tile<128xf64> -> tile<f64> (%27: tile<f64>, %28: tile<f64>) {
        %29 = maxf %27, %28 : tile<f64>
        yield %29 : tile<f64>
      }
      %30 = constant <f64: 1.0E-12> : tile<f64>
      %31 = cmpf greater_than ordered %30, %26 : tile<f64> -> tile<i1>
      %32 = divf %11, %20 rounding<nearest_even> : tile<128xf64>
      %33 = addf %20, %32 rounding<nearest_even> : tile<128xf64>
      %34 = mulf %13, %33 rounding<nearest_even> : tile<128xf64>
      %35 = addf %21, %14 rounding<nearest_even> : tile<128xf64>
      if %31 {
        break %20, %21, %22 : tile<128xf64>, tile<128xf64>, token
      } else {
        yield
      }
      continue %34, %35, %22 : tile<128xf64>, tile<128xf64>, token
    }
    %36 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %37 = broadcast %36 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %38 = offset %37, %7 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %39 = store_ptr_tko weak %38, %17 token=%19 : tile<128xptr<f64>>, tile<128xf64> -> token
    %40 = constant <i32: 1> : tile<i32>
    %41 = constant <i32: 128> : tile<i32>
    %42 = muli %40, %41 : tile<i32>
    %43 = reshape %42 : tile<i32> -> tile<1xi32>
    %44 = broadcast %43 : tile<1xi32> -> tile<128xi32>
    %45 = iota : tile<128xi32>
    %46 = addi %44, %45 : tile<128xi32>
    %47 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %48 = broadcast %47 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %49 = offset %48, %46 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %50 = store_ptr_tko weak %49, %18 token=%39 : tile<128xptr<f64>>, tile<128xf64> -> token
    return
  }
}
