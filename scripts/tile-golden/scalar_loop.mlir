cuda_tile.module @m {
  entry @scalar_loop(%arg0: tile<ptr<f64>>, %arg1: tile<i32>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <f64: 0.0> : tile<128xf64>
    %2 = constant <i32: 0> : tile<i32>
    %3 = constant <i32: 1> : tile<i32>
    %4, %5 = for %6 in (%2 to %arg1, step %3) : tile<i32> iter_values(%7 = %1, %8 = %0) -> (tile<128xf64>, token) {
      %9 = constant <i32: 128> : tile<i32>
      %10 = muli %6, %9 : tile<i32>
      %11 = reshape %10 : tile<i32> -> tile<1xi32>
      %12 = broadcast %11 : tile<1xi32> -> tile<128xi32>
      %13 = iota : tile<128xi32>
      %14 = addi %12, %13 : tile<128xi32>
      %15 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
      %16 = broadcast %15 : tile<1xptr<f64>> -> tile<128xptr<f64>>
      %17 = offset %16, %14 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
      %18, %19 = load_ptr_tko weak %17 token=%8 : tile<128xptr<f64>> -> tile<128xf64>, token
      %20 = addf %7, %18 rounding<nearest_even> : tile<128xf64>
      continue %20, %19 : tile<128xf64>, token
    }
    %21, %22, %23 = get_tile_block_id : tile<i32>
    %24 = constant <i32: 128> : tile<i32>
    %25 = muli %21, %24 : tile<i32>
    %26 = reshape %25 : tile<i32> -> tile<1xi32>
    %27 = broadcast %26 : tile<1xi32> -> tile<128xi32>
    %28 = iota : tile<128xi32>
    %29 = addi %27, %28 : tile<128xi32>
    %30 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %31 = broadcast %30 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %32 = offset %31, %29 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %33 = store_ptr_tko weak %32, %4 token=%5 : tile<128xptr<f64>>, tile<128xf64> -> token
    return
  }
}
