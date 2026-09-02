cuda_tile.module @m {
  entry @rms_norm(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 1024> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<1024xi32>
    %8 = iota : tile<1024xi32>
    %9 = addi %7, %8 : tile<1024xi32>
    %10 = constant <i32: 1000> : tile<1024xi32>
    %11 = cmpi less_than %9, %10, signed : tile<1024xi32> -> tile<1024xi1>
    %12 = constant <f64: 0.0> : tile<1024xf64>
    %13 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %14 = broadcast %13 : tile<1xptr<f64>> -> tile<1024xptr<f64>>
    %15 = offset %14, %9 : tile<1024xptr<f64>>, tile<1024xi32> -> tile<1024xptr<f64>>
    %16, %17 = load_ptr_tko weak %15, %11, %12 token=%0 : tile<1024xptr<f64>>, tile<1024xi1>, tile<1024xf64> -> tile<1024xf64>, token
    %18 = mulf %16, %16 rounding<nearest_even> : tile<1024xf64>
    %19 = reduce %18 dim=0 identities=[0.0 : f64] : tile<1024xf64> -> tile<f64> (%20: tile<f64>, %21: tile<f64>) {
      %22 = addf %20, %21 rounding<nearest_even> : tile<f64>
      yield %22 : tile<f64>
    }
    %23 = reshape %19 : tile<f64> -> tile<1xf64>
    %24 = broadcast %23 : tile<1xf64> -> tile<1024xf64>
    %25 = constant <f64: 1000.0> : tile<1024xf64>
    %26 = divf %24, %25 rounding<nearest_even> : tile<1024xf64>
    %27 = constant <f64: 1.0E-5> : tile<1024xf64>
    %28 = addf %26, %27 rounding<nearest_even> : tile<1024xf64>
    %29 = sqrt %28 rounding<nearest_even> : tile<1024xf64>
    %30 = divf %16, %29 rounding<nearest_even> : tile<1024xf64>
    %31 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %32 = broadcast %31 : tile<1xptr<f64>> -> tile<1024xptr<f64>>
    %33 = offset %32, %9 : tile<1024xptr<f64>>, tile<1024xi32> -> tile<1024xptr<f64>>
    %34 = store_ptr_tko weak %33, %30, %11 token=%17 : tile<1024xptr<f64>>, tile<1024xf64>, tile<1024xi1> -> token
    return
  }
}
