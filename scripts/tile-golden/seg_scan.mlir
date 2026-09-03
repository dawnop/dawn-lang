cuda_tile.module @m {
  entry @seg_scan(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<i32>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = reshape %1 : tile<i32> -> tile<1xi32>
    %3 = broadcast %2 : tile<1xi32> -> tile<128xi32>
    %4 = iota : tile<128xi32>
    %5 = addi %3, %4 : tile<128xi32>
    %6 = constant <i32: 100> : tile<128xi32>
    %7 = cmpi less_than %5, %6, signed : tile<128xi32> -> tile<128xi1>
    %8 = constant <f64: 0.0> : tile<128xf64>
    %9 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %10 = broadcast %9 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %11 = offset %10, %5 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %12, %13 = load_ptr_tko weak %11, %7, %8 token=%0 : tile<128xptr<f64>>, tile<128xi1>, tile<128xf64> -> tile<128xf64>, token
    %14 = constant <i32: 0> : tile<128xi32>
    %15 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %16 = broadcast %15 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %17 = offset %16, %5 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %18, %19 = load_ptr_tko weak %17, %7, %14 token=%13 : tile<128xptr<i32>>, tile<128xi1>, tile<128xi32> -> tile<128xi32>, token
    %20 = itof %18 signed rounding<nearest_even> : tile<128xi32> -> tile<128xf64>
    %21 = scan %12 dim=0 reverse=false identities=[0.0 : f64] : tile<128xf64> -> tile<128xf64> (%22: tile<f64>, %23: tile<f64>) {
      %24 = addf %22, %23 rounding<nearest_even> : tile<f64>
      yield %24 : tile<f64>
    }
    %25 = subf %21, %12 rounding<nearest_even> : tile<128xf64>
    %26, %27 = scan %20, %25 dim=0 reverse=false identities=[0.0 : f64, 0.0 : f64] : tile<128xf64>, tile<128xf64> -> tile<128xf64>, tile<128xf64> (%28: tile<f64>, %29: tile<f64>, %30: tile<f64>, %31: tile<f64>) {
      %32 = constant <f64: 0.5> : tile<f64>
      %33 = cmpf greater_than ordered %29, %32 : tile<f64> -> tile<i1>
      %34 = select %33, %29, %28 : tile<i1>, tile<f64>
      %35 = select %33, %31, %30 : tile<i1>, tile<f64>
      yield %34, %35 : tile<f64>, tile<f64>
    }
    %36 = subf %25, %27 rounding<nearest_even> : tile<128xf64>
    %37 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %38 = broadcast %37 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %39 = offset %38, %5 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %40 = store_ptr_tko weak %39, %36, %7 token=%19 : tile<128xptr<f64>>, tile<128xf64>, tile<128xi1> -> token
    return
  }
}
