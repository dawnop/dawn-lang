cuda_tile.module @m {
  entry @xattn_context(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7 = constant <i32: 32> : tile<i32>
    %8 = muli %6, %7 : tile<i32>
    %9 = constant <i32: 2048> : tile<i32>
    %10 = muli %6, %9 : tile<i32>
    %11 = constant <i32: 2048> : tile<i32>
    %12 = muli %1, %11 : tile<i32>
    %13 = addi %10, %12 : tile<i32>
    %14 = constant <i32: 0> : tile<i32>
    %15 = constant <i32: 2> : tile<i32>
    %16 = constant <i32: 1> : tile<i32>
    %17 = constant <f64: 0.0> : tile<32x32xf64>
    %18, %19 = for %20 in (%14 to %15, step %16) : tile<i32> iter_values(%21 = %17, %22 = %0) -> (tile<32x32xf64>, token) {
      %23 = constant <i32: 32> : tile<i32>
      %24 = muli %20, %23 : tile<i32>
      %25 = addi %13, %24 : tile<i32>
      %26 = reshape %25 : tile<i32> -> tile<1x1xi32>
      %27 = broadcast %26 : tile<1x1xi32> -> tile<32x32xi32>
      %28 = iota : tile<32xi32>
      %29 = reshape %28 : tile<32xi32> -> tile<32x1xi32>
      %30 = broadcast %29 : tile<32x1xi32> -> tile<32x32xi32>
      %31 = constant <i32: 64> : tile<32x32xi32>
      %32 = muli %30, %31 : tile<32x32xi32>
      %33 = addi %27, %32 : tile<32x32xi32>
      %34 = iota : tile<32xi32>
      %35 = reshape %34 : tile<32xi32> -> tile<1x32xi32>
      %36 = broadcast %35 : tile<1x32xi32> -> tile<32x32xi32>
      %37 = addi %33, %36 : tile<32x32xi32>
      %38 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
      %39 = broadcast %38 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
      %40 = offset %39, %37 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
      %41, %42 = load_ptr_tko weak %40 token=%22 : tile<32x32xptr<f64>> -> tile<32x32xf64>, token
      %43 = constant <i32: 2048> : tile<i32>
      %44 = muli %20, %43 : tile<i32>
      %45 = addi %44, %8 : tile<i32>
      %46 = reshape %45 : tile<i32> -> tile<1x1xi32>
      %47 = broadcast %46 : tile<1x1xi32> -> tile<32x32xi32>
      %48 = iota : tile<32xi32>
      %49 = reshape %48 : tile<32xi32> -> tile<32x1xi32>
      %50 = broadcast %49 : tile<32x1xi32> -> tile<32x32xi32>
      %51 = constant <i32: 64> : tile<32x32xi32>
      %52 = muli %50, %51 : tile<32x32xi32>
      %53 = addi %47, %52 : tile<32x32xi32>
      %54 = iota : tile<32xi32>
      %55 = reshape %54 : tile<32xi32> -> tile<1x32xi32>
      %56 = broadcast %55 : tile<1x32xi32> -> tile<32x32xi32>
      %57 = addi %53, %56 : tile<32x32xi32>
      %58 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
      %59 = broadcast %58 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
      %60 = offset %59, %57 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
      %61, %62 = load_ptr_tko weak %60 token=%42 : tile<32x32xptr<f64>> -> tile<32x32xf64>, token
      %63 = mmaf %41, %61, %21 : tile<32x32xf64>, tile<32x32xf64>, tile<32x32xf64>
      continue %63, %62 : tile<32x32xf64>, token
    }
    %64 = constant <i32: 2048> : tile<i32>
    %65 = muli %1, %64 : tile<i32>
    %66 = addi %65, %8 : tile<i32>
    %67 = reshape %66 : tile<i32> -> tile<1x1xi32>
    %68 = broadcast %67 : tile<1x1xi32> -> tile<32x32xi32>
    %69 = iota : tile<32xi32>
    %70 = reshape %69 : tile<32xi32> -> tile<32x1xi32>
    %71 = broadcast %70 : tile<32x1xi32> -> tile<32x32xi32>
    %72 = constant <i32: 64> : tile<32x32xi32>
    %73 = muli %71, %72 : tile<32x32xi32>
    %74 = addi %68, %73 : tile<32x32xi32>
    %75 = iota : tile<32xi32>
    %76 = reshape %75 : tile<32xi32> -> tile<1x32xi32>
    %77 = broadcast %76 : tile<1x32xi32> -> tile<32x32xi32>
    %78 = addi %74, %77 : tile<32x32xi32>
    %79 = reshape %arg2 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %80 = broadcast %79 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
    %81 = offset %80, %78 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
    %82 = store_ptr_tko weak %81, %18 token=%19 : tile<32x32xptr<f64>>, tile<32x32xf64> -> token
    return
  }
}
