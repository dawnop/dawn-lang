cuda_tile.module @m {
  entry @sum(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 4> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = constant <i32: 128> : tile<i32>
    %7 = muli %5, %6 : tile<i32>
    %8 = reshape %7 : tile<i32> -> tile<1xi32>
    %9 = broadcast %8 : tile<1xi32> -> tile<128xi32>
    %10 = iota : tile<128xi32>
    %11 = addi %9, %10 : tile<128xi32>
    %12 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %13 = broadcast %12 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %14 = offset %13, %11 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %15, %16 = load_ptr_tko weak %14 token=%0 : tile<128xptr<f64>> -> tile<128xf64>, token
    %17 = constant <i32: 1> : tile<i32>
    %18 = addi %5, %17 : tile<i32>
    %19 = addi %5, %4 : tile<i32>
    %20, %21 = for %22 in (%18 to %19, step %17) : tile<i32> iter_values(%23 = %15, %24 = %16) -> (tile<128xf64>, token) {
      %25 = constant <i32: 128> : tile<i32>
      %26 = muli %22, %25 : tile<i32>
      %27 = reshape %26 : tile<i32> -> tile<1xi32>
      %28 = broadcast %27 : tile<1xi32> -> tile<128xi32>
      %29 = iota : tile<128xi32>
      %30 = addi %28, %29 : tile<128xi32>
      %31 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
      %32 = broadcast %31 : tile<1xptr<f64>> -> tile<128xptr<f64>>
      %33 = offset %32, %30 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
      %34, %35 = load_ptr_tko weak %33 token=%24 : tile<128xptr<f64>> -> tile<128xf64>, token
      %36 = addf %23, %34 rounding<nearest_even> : tile<128xf64>
      continue %36, %35 : tile<128xf64>, token
    }
    %37 = constant <i32: 128> : tile<i32>
    %38 = muli %1, %37 : tile<i32>
    %39 = reshape %38 : tile<i32> -> tile<1xi32>
    %40 = broadcast %39 : tile<1xi32> -> tile<128xi32>
    %41 = iota : tile<128xi32>
    %42 = addi %40, %41 : tile<128xi32>
    %43 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %44 = broadcast %43 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %45 = offset %44, %42 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %46 = store_ptr_tko weak %45, %20 token=%21 : tile<128xptr<f64>>, tile<128xf64> -> token
    return
  }
}
