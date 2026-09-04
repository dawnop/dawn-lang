cuda_tile.module @m {
  entry @attn_context(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <f64: 0.0> : tile<32x32xf64>
    %5 = constant <i32: 0> : tile<i32>
    %6 = constant <i32: 2> : tile<i32>
    %7 = constant <i32: 1> : tile<i32>
    %8, %9 = for %10 in (%5 to %6, step %7) : tile<i32> iter_values(%11 = %4, %12 = %0) -> (tile<32x32xf64>, token) {
      %13 = constant <i32: 2048> : tile<i32>
      %14 = muli %1, %13 : tile<i32>
      %15 = constant <i32: 32> : tile<i32>
      %16 = muli %10, %15 : tile<i32>
      %17 = addi %14, %16 : tile<i32>
      %18 = reshape %17 : tile<i32> -> tile<1x1xi32>
      %19 = broadcast %18 : tile<1x1xi32> -> tile<32x32xi32>
      %20 = iota : tile<32xi32>
      %21 = reshape %20 : tile<32xi32> -> tile<32x1xi32>
      %22 = broadcast %21 : tile<32x1xi32> -> tile<32x32xi32>
      %23 = constant <i32: 64> : tile<32x32xi32>
      %24 = muli %22, %23 : tile<32x32xi32>
      %25 = addi %19, %24 : tile<32x32xi32>
      %26 = iota : tile<32xi32>
      %27 = reshape %26 : tile<32xi32> -> tile<1x32xi32>
      %28 = broadcast %27 : tile<1x32xi32> -> tile<32x32xi32>
      %29 = addi %25, %28 : tile<32x32xi32>
      %30 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
      %31 = broadcast %30 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
      %32 = offset %31, %29 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
      %33, %34 = load_ptr_tko weak %32 token=%12 : tile<32x32xptr<f64>> -> tile<32x32xf64>, token
      %35 = constant <i32: 1024> : tile<i32>
      %36 = muli %10, %35 : tile<i32>
      %37 = reshape %36 : tile<i32> -> tile<1x1xi32>
      %38 = broadcast %37 : tile<1x1xi32> -> tile<32x32xi32>
      %39 = iota : tile<32xi32>
      %40 = reshape %39 : tile<32xi32> -> tile<32x1xi32>
      %41 = broadcast %40 : tile<32x1xi32> -> tile<32x32xi32>
      %42 = constant <i32: 32> : tile<32x32xi32>
      %43 = muli %41, %42 : tile<32x32xi32>
      %44 = addi %38, %43 : tile<32x32xi32>
      %45 = iota : tile<32xi32>
      %46 = reshape %45 : tile<32xi32> -> tile<1x32xi32>
      %47 = broadcast %46 : tile<1x32xi32> -> tile<32x32xi32>
      %48 = addi %44, %47 : tile<32x32xi32>
      %49 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
      %50 = broadcast %49 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
      %51 = offset %50, %48 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
      %52, %53 = load_ptr_tko weak %51 token=%34 : tile<32x32xptr<f64>> -> tile<32x32xf64>, token
      %54 = mmaf %33, %52, %11 : tile<32x32xf64>, tile<32x32xf64>, tile<32x32xf64>
      continue %54, %53 : tile<32x32xf64>, token
    }
    %55 = constant <i32: 1024> : tile<i32>
    %56 = muli %1, %55 : tile<i32>
    %57 = reshape %56 : tile<i32> -> tile<1x1xi32>
    %58 = broadcast %57 : tile<1x1xi32> -> tile<32x32xi32>
    %59 = iota : tile<32xi32>
    %60 = reshape %59 : tile<32xi32> -> tile<32x1xi32>
    %61 = broadcast %60 : tile<32x1xi32> -> tile<32x32xi32>
    %62 = constant <i32: 32> : tile<32x32xi32>
    %63 = muli %61, %62 : tile<32x32xi32>
    %64 = addi %58, %63 : tile<32x32xi32>
    %65 = iota : tile<32xi32>
    %66 = reshape %65 : tile<32xi32> -> tile<1x32xi32>
    %67 = broadcast %66 : tile<1x32xi32> -> tile<32x32xi32>
    %68 = addi %64, %67 : tile<32x32xi32>
    %69 = reshape %arg2 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %70 = broadcast %69 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
    %71 = offset %70, %68 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
    %72 = store_ptr_tko weak %71, %8 token=%9 : tile<32x32xptr<f64>>, tile<32x32xf64> -> token
    return
  }
}
