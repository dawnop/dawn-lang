cuda_tile.module @m {
  entry @lora_out(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <f64: 0.0> : tile<32x32xf64>
    %5 = constant <i32: 0> : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1x1xi32>
    %7 = broadcast %6 : tile<1x1xi32> -> tile<32x16xi32>
    %8 = iota : tile<32xi32>
    %9 = reshape %8 : tile<32xi32> -> tile<32x1xi32>
    %10 = broadcast %9 : tile<32x1xi32> -> tile<32x16xi32>
    %11 = constant <i32: 16> : tile<32x16xi32>
    %12 = muli %10, %11 : tile<32x16xi32>
    %13 = addi %7, %12 : tile<32x16xi32>
    %14 = iota : tile<16xi32>
    %15 = reshape %14 : tile<16xi32> -> tile<1x16xi32>
    %16 = broadcast %15 : tile<1x16xi32> -> tile<32x16xi32>
    %17 = addi %13, %16 : tile<32x16xi32>
    %18 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %19 = broadcast %18 : tile<1x1xptr<f64>> -> tile<32x16xptr<f64>>
    %20 = offset %19, %17 : tile<32x16xptr<f64>>, tile<32x16xi32> -> tile<32x16xptr<f64>>
    %21, %22 = load_ptr_tko weak %20 token=%0 : tile<32x16xptr<f64>> -> tile<32x16xf64>, token
    %23 = constant <i32: 512> : tile<i32>
    %24 = muli %2, %23 : tile<i32>
    %25 = reshape %24 : tile<i32> -> tile<1x1xi32>
    %26 = broadcast %25 : tile<1x1xi32> -> tile<16x32xi32>
    %27 = iota : tile<16xi32>
    %28 = reshape %27 : tile<16xi32> -> tile<16x1xi32>
    %29 = broadcast %28 : tile<16x1xi32> -> tile<16x32xi32>
    %30 = addi %26, %29 : tile<16x32xi32>
    %31 = iota : tile<32xi32>
    %32 = reshape %31 : tile<32xi32> -> tile<1x32xi32>
    %33 = broadcast %32 : tile<1x32xi32> -> tile<16x32xi32>
    %34 = constant <i32: 16> : tile<16x32xi32>
    %35 = muli %33, %34 : tile<16x32xi32>
    %36 = addi %30, %35 : tile<16x32xi32>
    %37 = reshape %arg2 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %38 = broadcast %37 : tile<1x1xptr<f64>> -> tile<16x32xptr<f64>>
    %39 = offset %38, %36 : tile<16x32xptr<f64>>, tile<16x32xi32> -> tile<16x32xptr<f64>>
    %40, %41 = load_ptr_tko weak %39 token=%22 : tile<16x32xptr<f64>> -> tile<16x32xf64>, token
    %42 = mmaf %21, %40, %4 : tile<32x16xf64>, tile<16x32xf64>, tile<32x32xf64>
    %43 = constant <i32: 32> : tile<i32>
    %44 = muli %2, %43 : tile<i32>
    %45 = reshape %44 : tile<i32> -> tile<1x1xi32>
    %46 = broadcast %45 : tile<1x1xi32> -> tile<32x32xi32>
    %47 = iota : tile<32xi32>
    %48 = reshape %47 : tile<32xi32> -> tile<32x1xi32>
    %49 = broadcast %48 : tile<32x1xi32> -> tile<32x32xi32>
    %50 = constant <i32: 64> : tile<32x32xi32>
    %51 = muli %49, %50 : tile<32x32xi32>
    %52 = addi %46, %51 : tile<32x32xi32>
    %53 = iota : tile<32xi32>
    %54 = reshape %53 : tile<32xi32> -> tile<1x32xi32>
    %55 = broadcast %54 : tile<1x32xi32> -> tile<32x32xi32>
    %56 = addi %52, %55 : tile<32x32xi32>
    %57 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %58 = broadcast %57 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
    %59 = offset %58, %56 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
    %60, %61 = load_ptr_tko weak %59 token=%41 : tile<32x32xptr<f64>> -> tile<32x32xf64>, token
    %62 = constant <i32: 32> : tile<i32>
    %63 = muli %2, %62 : tile<i32>
    %64 = constant <f64: 0.5> : tile<32x32xf64>
    %65 = mulf %64, %42 rounding<nearest_even> : tile<32x32xf64>
    %66 = addf %60, %65 rounding<nearest_even> : tile<32x32xf64>
    %67 = reshape %63 : tile<i32> -> tile<1x1xi32>
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
    %79 = reshape %arg3 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %80 = broadcast %79 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
    %81 = offset %80, %78 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
    %82 = store_ptr_tko weak %81, %66 token=%61 : tile<32x32xptr<f64>>, tile<32x32xf64> -> token
    return
  }
}
