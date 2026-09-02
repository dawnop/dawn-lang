cuda_tile.module @m {
  entry @foldif(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 4> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = constant <i32: 1> : tile<i32>
    %7 = constant <i32: 128> : tile<i32>
    %8 = muli %5, %7 : tile<i32>
    %9 = reshape %8 : tile<i32> -> tile<1xi32>
    %10 = broadcast %9 : tile<1xi32> -> tile<128xi32>
    %11 = iota : tile<128xi32>
    %12 = addi %10, %11 : tile<128xi32>
    %13 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %14 = broadcast %13 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %15 = offset %14, %12 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %16, %17 = load_ptr_tko weak %15 token=%0 : tile<128xptr<f64>> -> tile<128xf64>, token
    %18 = addi %5, %6 : tile<i32>
    %19 = addi %5, %4 : tile<i32>
    %20, %21, %22, %23 = for %24 in (%18 to %19, step %6) : tile<i32> iter_values(%25 = %16, %26 = %16, %27 = %16, %28 = %17) -> (tile<128xf64>, tile<128xf64>, tile<128xf64>, token) {
      %29 = constant <i32: 128> : tile<i32>
      %30 = muli %24, %29 : tile<i32>
      %31 = reshape %30 : tile<i32> -> tile<1xi32>
      %32 = broadcast %31 : tile<1xi32> -> tile<128xi32>
      %33 = iota : tile<128xi32>
      %34 = addi %32, %33 : tile<128xi32>
      %35 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
      %36 = broadcast %35 : tile<1xptr<f64>> -> tile<128xptr<f64>>
      %37 = offset %36, %34 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
      %38, %39 = load_ptr_tko weak %37 token=%28 : tile<128xptr<f64>> -> tile<128xf64>, token
      %40 = addf %25, %38 rounding<nearest_even> : tile<128xf64>
      %41 = maxf %26, %38 : tile<128xf64>
      %42 = minf %27, %38 : tile<128xf64>
      continue %40, %41, %42, %39 : tile<128xf64>, tile<128xf64>, tile<128xf64>, token
    }
    %43 = constant <i32: 0> : tile<i32>
    %44 = cmpi equal %1, %43, signed : tile<i32> -> tile<i1>
    %45 = if %44 -> (tile<128xf64>) {
      yield %20 : tile<128xf64>
    } else {
      %46 = subf %21, %22 rounding<nearest_even> : tile<128xf64>
      yield %46 : tile<128xf64>
    }
    %47 = constant <i32: 128> : tile<i32>
    %48 = muli %1, %47 : tile<i32>
    %49 = reshape %48 : tile<i32> -> tile<1xi32>
    %50 = broadcast %49 : tile<1xi32> -> tile<128xi32>
    %51 = iota : tile<128xi32>
    %52 = addi %50, %51 : tile<128xi32>
    %53 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %54 = broadcast %53 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %55 = offset %54, %52 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %56 = store_ptr_tko weak %55, %45 token=%23 : tile<128xptr<f64>>, tile<128xf64> -> token
    return
  }
}
