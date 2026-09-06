cuda_tile.module @m {
  entry @dtype_i4(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>, %arg2: tile<ptr<i32>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 32> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<32xi32>
    %8 = iota : tile<32xi32>
    %9 = addi %7, %8 : tile<32xi32>
    %10 = reshape %arg0 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %11 = broadcast %10 : tile<1xptr<i32>> -> tile<32xptr<i32>>
    %12 = offset %11, %9 : tile<32xptr<i32>>, tile<32xi32> -> tile<32xptr<i32>>
    %13, %14 = load_ptr_tko weak %12 token=%0 : tile<32xptr<i32>> -> tile<32xi32>, token
    %15 = pack %13 : tile<32xi32> -> tile<128xi8>
    %16 = unpack %15 : tile<128xi8> -> tile<256xi4>
    %17 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %18 = broadcast %17 : tile<1xptr<i32>> -> tile<32xptr<i32>>
    %19 = offset %18, %9 : tile<32xptr<i32>>, tile<32xi32> -> tile<32xptr<i32>>
    %20, %21 = load_ptr_tko weak %19 token=%14 : tile<32xptr<i32>> -> tile<32xi32>, token
    %22 = pack %20 : tile<32xi32> -> tile<128xi8>
    %23 = unpack %22 : tile<128xi8> -> tile<256xi4>
    %24 = exti %16 signed : tile<256xi4> -> tile<256xi32>
    %25 = exti %23 signed : tile<256xi4> -> tile<256xi32>
    %26 = exti %16 unsigned : tile<256xi4> -> tile<256xi32>
    %27 = iota : tile<256xi32>
    %28 = trunci %27 : tile<256xi32> -> tile<256xi1>
    %29 = constant <i32: 0> : tile<i32>
    %30 = addi %5, %29 : tile<i32>
    %31 = addi %24, %25 : tile<256xi32>
    %32 = trunci %31 : tile<256xi32> -> tile<256xi4>
    %33 = pack %32 : tile<256xi4> -> tile<128xi8>
    %34 = unpack %33 : tile<128xi8> -> tile<32xi32>
    %35 = reshape %30 : tile<i32> -> tile<1xi32>
    %36 = broadcast %35 : tile<1xi32> -> tile<32xi32>
    %37 = iota : tile<32xi32>
    %38 = addi %36, %37 : tile<32xi32>
    %39 = reshape %arg2 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %40 = broadcast %39 : tile<1xptr<i32>> -> tile<32xptr<i32>>
    %41 = offset %40, %38 : tile<32xptr<i32>>, tile<32xi32> -> tile<32xptr<i32>>
    %42 = store_ptr_tko weak %41, %34 token=%21 : tile<32xptr<i32>>, tile<32xi32> -> token
    %43 = constant <i32: 512> : tile<i32>
    %44 = addi %5, %43 : tile<i32>
    %45 = constant <i32: 1> : tile<256xi32>
    %46 = shri %24, %45 signed : tile<256xi32>
    %47 = trunci %46 : tile<256xi32> -> tile<256xi4>
    %48 = pack %47 : tile<256xi4> -> tile<128xi8>
    %49 = unpack %48 : tile<128xi8> -> tile<32xi32>
    %50 = reshape %44 : tile<i32> -> tile<1xi32>
    %51 = broadcast %50 : tile<1xi32> -> tile<32xi32>
    %52 = iota : tile<32xi32>
    %53 = addi %51, %52 : tile<32xi32>
    %54 = reshape %arg2 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %55 = broadcast %54 : tile<1xptr<i32>> -> tile<32xptr<i32>>
    %56 = offset %55, %53 : tile<32xptr<i32>>, tile<32xi32> -> tile<32xptr<i32>>
    %57 = store_ptr_tko weak %56, %49 token=%42 : tile<32xptr<i32>>, tile<32xi32> -> token
    %58 = constant <i32: 1024> : tile<i32>
    %59 = addi %5, %58 : tile<i32>
    %60 = constant <i32: 1> : tile<256xi32>
    %61 = shri %26, %60 signed : tile<256xi32>
    %62 = trunci %61 : tile<256xi32> -> tile<256xi4>
    %63 = pack %62 : tile<256xi4> -> tile<128xi8>
    %64 = unpack %63 : tile<128xi8> -> tile<32xi32>
    %65 = reshape %59 : tile<i32> -> tile<1xi32>
    %66 = broadcast %65 : tile<1xi32> -> tile<32xi32>
    %67 = iota : tile<32xi32>
    %68 = addi %66, %67 : tile<32xi32>
    %69 = reshape %arg2 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %70 = broadcast %69 : tile<1xptr<i32>> -> tile<32xptr<i32>>
    %71 = offset %70, %68 : tile<32xptr<i32>>, tile<32xi32> -> tile<32xptr<i32>>
    %72 = store_ptr_tko weak %71, %64 token=%57 : tile<32xptr<i32>>, tile<32xi32> -> token
    %73 = constant <i32: 1536> : tile<i32>
    %74 = addi %5, %73 : tile<i32>
    %75 = muli %24, %25 : tile<256xi32>
    %76 = trunci %75 : tile<256xi32> -> tile<256xi4>
    %77 = pack %76 : tile<256xi4> -> tile<128xi8>
    %78 = unpack %77 : tile<128xi8> -> tile<32xi32>
    %79 = reshape %74 : tile<i32> -> tile<1xi32>
    %80 = broadcast %79 : tile<1xi32> -> tile<32xi32>
    %81 = iota : tile<32xi32>
    %82 = addi %80, %81 : tile<32xi32>
    %83 = reshape %arg2 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %84 = broadcast %83 : tile<1xptr<i32>> -> tile<32xptr<i32>>
    %85 = offset %84, %82 : tile<32xptr<i32>>, tile<32xi32> -> tile<32xptr<i32>>
    %86 = store_ptr_tko weak %85, %78 token=%72 : tile<32xptr<i32>>, tile<32xi32> -> token
    %87 = constant <i32: 2048> : tile<i32>
    %88 = addi %5, %87 : tile<i32>
    %89 = select %28, %25, %24 : tile<256xi1>, tile<256xi32>
    %90 = trunci %89 : tile<256xi32> -> tile<256xi4>
    %91 = pack %90 : tile<256xi4> -> tile<128xi8>
    %92 = unpack %91 : tile<128xi8> -> tile<32xi32>
    %93 = reshape %88 : tile<i32> -> tile<1xi32>
    %94 = broadcast %93 : tile<1xi32> -> tile<32xi32>
    %95 = iota : tile<32xi32>
    %96 = addi %94, %95 : tile<32xi32>
    %97 = reshape %arg2 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %98 = broadcast %97 : tile<1xptr<i32>> -> tile<32xptr<i32>>
    %99 = offset %98, %96 : tile<32xptr<i32>>, tile<32xi32> -> tile<32xptr<i32>>
    %100 = store_ptr_tko weak %99, %92 token=%86 : tile<32xptr<i32>>, tile<32xi32> -> token
    return
  }
}
