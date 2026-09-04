cuda_tile.module @m {
  entry @kv_context(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<i8>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 64> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1x1xi32>
    %7 = broadcast %6 : tile<1x1xi32> -> tile<64x32xi32>
    %8 = iota : tile<64xi32>
    %9 = reshape %8 : tile<64xi32> -> tile<64x1xi32>
    %10 = broadcast %9 : tile<64x1xi32> -> tile<64x32xi32>
    %11 = addi %7, %10 : tile<64x32xi32>
    %12 = iota : tile<32xi32>
    %13 = reshape %12 : tile<32xi32> -> tile<1x32xi32>
    %14 = broadcast %13 : tile<1x32xi32> -> tile<64x32xi32>
    %15 = constant <i32: 0> : tile<64x32xi32>
    %16 = muli %14, %15 : tile<64x32xi32>
    %17 = addi %11, %16 : tile<64x32xi32>
    %18 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %19 = broadcast %18 : tile<1x1xptr<f64>> -> tile<64x32xptr<f64>>
    %20 = offset %19, %17 : tile<64x32xptr<f64>>, tile<64x32xi32> -> tile<64x32xptr<f64>>
    %21, %22 = load_ptr_tko weak %20 token=%0 : tile<64x32xptr<f64>> -> tile<64x32xf64>, token
    %23 = constant <i32: 2048> : tile<i32>
    %24 = muli %1, %23 : tile<i32>
    %25 = reshape %24 : tile<i32> -> tile<1x1xi32>
    %26 = broadcast %25 : tile<1x1xi32> -> tile<64x32xi32>
    %27 = iota : tile<64xi32>
    %28 = reshape %27 : tile<64xi32> -> tile<64x1xi32>
    %29 = broadcast %28 : tile<64x1xi32> -> tile<64x32xi32>
    %30 = constant <i32: 32> : tile<64x32xi32>
    %31 = muli %29, %30 : tile<64x32xi32>
    %32 = addi %26, %31 : tile<64x32xi32>
    %33 = iota : tile<32xi32>
    %34 = reshape %33 : tile<32xi32> -> tile<1x32xi32>
    %35 = broadcast %34 : tile<1x32xi32> -> tile<64x32xi32>
    %36 = addi %32, %35 : tile<64x32xi32>
    %37 = reshape %arg1 : tile<ptr<i8>> -> tile<1x1xptr<i8>>
    %38 = broadcast %37 : tile<1x1xptr<i8>> -> tile<64x32xptr<i8>>
    %39 = offset %38, %36 : tile<64x32xptr<i8>>, tile<64x32xi32> -> tile<64x32xptr<i8>>
    %40, %41 = load_ptr_tko weak %39 token=%22 : tile<64x32xptr<i8>> -> tile<64x32xi8>, token
    %42 = constant <i32: 64> : tile<i32>
    %43 = muli %1, %42 : tile<i32>
    %44 = reshape %43 : tile<i32> -> tile<1x1xi32>
    %45 = broadcast %44 : tile<1x1xi32> -> tile<64x32xi32>
    %46 = iota : tile<64xi32>
    %47 = reshape %46 : tile<64xi32> -> tile<64x1xi32>
    %48 = broadcast %47 : tile<64x1xi32> -> tile<64x32xi32>
    %49 = addi %45, %48 : tile<64x32xi32>
    %50 = iota : tile<32xi32>
    %51 = reshape %50 : tile<32xi32> -> tile<1x32xi32>
    %52 = broadcast %51 : tile<1x32xi32> -> tile<64x32xi32>
    %53 = constant <i32: 0> : tile<64x32xi32>
    %54 = muli %52, %53 : tile<64x32xi32>
    %55 = addi %49, %54 : tile<64x32xi32>
    %56 = reshape %arg2 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %57 = broadcast %56 : tile<1x1xptr<f64>> -> tile<64x32xptr<f64>>
    %58 = offset %57, %55 : tile<64x32xptr<f64>>, tile<64x32xi32> -> tile<64x32xptr<f64>>
    %59, %60 = load_ptr_tko weak %58 token=%41 : tile<64x32xptr<f64>> -> tile<64x32xf64>, token
    %61 = exti %40 unsigned : tile<64x32xi8> -> tile<64x32xi32>
    %62 = constant <i32: 128> : tile<64x32xi32>
    %63 = xori %61, %62 : tile<64x32xi32>
    %64 = constant <i32: 128> : tile<64x32xi32>
    %65 = subi %63, %64 : tile<64x32xi32>
    %66 = itof %65 signed rounding<nearest_even> : tile<64x32xi32> -> tile<64x32xf64>
    %67 = mulf %66, %59 rounding<nearest_even> : tile<64x32xf64>
    %68 = mulf %21, %67 rounding<nearest_even> : tile<64x32xf64>
    %69 = reduce %68 dim=0 identities=[0.0 : f64] : tile<64x32xf64> -> tile<32xf64> (%70: tile<f64>, %71: tile<f64>) {
      %72 = addf %70, %71 rounding<nearest_even> : tile<f64>
      yield %72 : tile<f64>
    }
    %73 = constant <i32: 32> : tile<i32>
    %74 = muli %1, %73 : tile<i32>
    %75 = reshape %74 : tile<i32> -> tile<1xi32>
    %76 = broadcast %75 : tile<1xi32> -> tile<32xi32>
    %77 = iota : tile<32xi32>
    %78 = addi %76, %77 : tile<32xi32>
    %79 = reshape %arg3 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %80 = broadcast %79 : tile<1xptr<f64>> -> tile<32xptr<f64>>
    %81 = offset %80, %78 : tile<32xptr<f64>>, tile<32xi32> -> tile<32xptr<f64>>
    %82 = store_ptr_tko weak %81, %69 token=%60 : tile<32xptr<f64>>, tile<32xf64> -> token
    return
  }
}
